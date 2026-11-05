#!/usr/bin/env python3
"""Validate, build and publish the compositor resource pack.

    python3 tools/build_pack.py                 # validate + build build/wl-pack-<hash>.zip
    python3 tools/build_pack.py --check         # validate only
    python3 tools/build_pack.py --publish       # build, then commit the zip to the local pack-dist branch
    python3 tools/build_pack.py --publish --push

Validation:
  * pack.mcmeta declares min_format/max_format covering the target format.
  * Every .json/.mcmeta parses (no duplicate keys) and every asset path is a
    valid resource location (lowercase a-z 0-9 _ - . /), since the game skips
    files with bad names without an error.
  * Every shader under assets/*/shaders/ compiles with glslc the way the 26.3
    client compiles it (shaderc, Vulkan 1.2, auto-bound uniforms, includes as
    <namespace:path.glsl>), under each define set in tools/shader_variants.json.
    Vanilla includes come from the 26.3 client jar or an extracted assets dir
    (--vanilla, $MC_VANILLA, or the usual launcher locations); they are never
    copied into this repo.

Build: a deterministic zip of pack.mcmeta, pack.png and assets/ (pack/src/ and
dotfiles are left out). The file name carries a hash of the content, so an
unchanged pack keeps its name and any change gets a new one; DF's
sendResourcePack takes only a URL, so the name is what stops clients reusing a
cached pack.

Publish: adds the zip and latest.json to the orphan pack-dist branch with git
plumbing (the working tree is not touched). The pack then loads from
https://raw.githubusercontent.com/<owner>/<repo>/pack-dist/<file>.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import io
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "pack"
BUILD = ROOT / "build"
VARIANTS = Path(__file__).resolve().parent / "shader_variants.json"

TARGET_FORMAT = (97, 1)  # Minecraft 26.3
MC_VERSION = "26.3"
DIST_BRANCH = "pack-dist"
ZIP_PREFIX = "wl-pack-"

# Files that go into the zip, relative to pack/.
TOP_FILES = ("pack.mcmeta", "pack.png")
TOP_DIRS = ("assets",)

STAGES = {".vsh": "vert", ".fsh": "frag"}
INCLUDE_RE = re.compile(r'^(\s*#\s*include\s+)<([a-z0-9_.-]+):([a-z0-9_./-]+)>(.*)$')
PATH_RE = re.compile(r"^[a-z0-9_.-]+(/[a-z0-9_.-]+)*$")
# Like the client: Vulkan 1.2 target, auto-bound uniforms, no optimisation.
GLSLC_ARGS = ["--target-env=vulkan1.2", "-fauto-bind-uniforms", "-O0"]


class BuildError(Exception):
    pass


# ---------------------------------------------------------------- files


def pack_files() -> list[Path]:
    """Every file that goes into the zip, sorted, relative to pack/."""
    out = []
    for name in TOP_FILES:
        if (PACK / name).is_file():
            out.append(Path(name))
    for top in TOP_DIRS:
        base = PACK / top
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            rel = path.relative_to(PACK)
            if path.is_file() and not any(part.startswith(".") for part in rel.parts):
                out.append(rel)
    return sorted(out, key=lambda p: p.as_posix())


def load_json(path: Path):
    """Parse JSON, rejecting duplicate keys."""

    def no_dupes(pairs):
        seen = {}
        for key, value in pairs:
            if key in seen:
                raise ValueError(f"duplicate key {key!r}")
            seen[key] = value
        return seen

    with path.open(encoding="utf-8") as f:
        return json.load(f, object_pairs_hook=no_dupes)


# ---------------------------------------------------------------- checks


def parse_format(value, what: str) -> tuple[int, int]:
    if isinstance(value, int):
        return (value, 0)
    if isinstance(value, list) and 1 <= len(value) <= 2 and all(isinstance(v, int) for v in value):
        return (value[0], value[1] if len(value) == 2 else 0)
    raise BuildError(f"pack.mcmeta: {what} must be an int or [major, minor], got {value!r}")


def check_mcmeta() -> dict:
    path = PACK / "pack.mcmeta"
    if not path.is_file():
        raise BuildError("pack/pack.mcmeta is missing")
    meta = load_json(path)
    pack = meta.get("pack")
    if not isinstance(pack, dict):
        raise BuildError("pack.mcmeta: missing 'pack' object")
    if "description" not in pack:
        raise BuildError("pack.mcmeta: missing pack.description")
    if "min_format" not in pack or "max_format" not in pack:
        raise BuildError("pack.mcmeta: pack format 65+ needs both min_format and max_format")
    if "supported_formats" in pack:
        raise BuildError("pack.mcmeta: supported_formats is rejected from format 65 on; remove it")
    lo = parse_format(pack["min_format"], "min_format")
    hi = parse_format(pack["max_format"], "max_format")
    if not lo <= TARGET_FORMAT <= hi:
        raise BuildError(
            f"pack.mcmeta: format range {lo[0]}.{lo[1]}..{hi[0]}.{hi[1]} does not include "
            f"{TARGET_FORMAT[0]}.{TARGET_FORMAT[1]} (Minecraft {MC_VERSION})"
        )
    return meta


def check_files(files: list[Path]) -> list[str]:
    errors = []
    for rel in files:
        if rel.parts[0] == "assets":
            inner = rel.relative_to("assets").as_posix()
            if not PATH_RE.match(inner):
                errors.append(f"{rel}: not a valid resource location (lowercase a-z 0-9 _ - . / only)")
        if rel.suffix in (".json", ".mcmeta"):
            try:
                load_json(PACK / rel)
            except (ValueError, UnicodeDecodeError) as e:
                errors.append(f"{rel}: {e}")
    return errors


# ---------------------------------------------------------------- shaders


def find_vanilla(explicit: str | None) -> Path | None:
    """Return a 26.3 client jar or a dir containing assets/minecraft/shaders."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if os.environ.get("MC_VANILLA"):
        candidates.append(Path(os.environ["MC_VANILLA"]).expanduser())
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData/Roaming"))
    candidates += [
        home / f".minecraft/versions/{MC_VERSION}/{MC_VERSION}.jar",
        appdata / f".minecraft/versions/{MC_VERSION}/{MC_VERSION}.jar",
        home / f"Library/Application Support/minecraft/versions/{MC_VERSION}/{MC_VERSION}.jar",
        home / f".local/share/PrismLauncher/libraries/com/mojang/minecraft/{MC_VERSION}/minecraft-{MC_VERSION}-client.jar",
        home / f".var/app/org.prismlauncher.PrismLauncher/data/PrismLauncher/libraries/com/mojang/minecraft/{MC_VERSION}/minecraft-{MC_VERSION}-client.jar",
    ]
    for c in candidates:
        if c.is_file() or (c / "assets/minecraft/shaders").is_dir():
            return c
    if explicit:
        raise BuildError(f"--vanilla {explicit}: not a client jar or a dir with assets/minecraft/shaders")
    return None


def stage_vanilla_includes(source: Path, dest: Path) -> None:
    """Copy vanilla shader includes into dest/<namespace>/<path>."""
    prefix = "assets/minecraft/shaders/include/"
    if source.is_file():
        with zipfile.ZipFile(source) as jar:
            for name in jar.namelist():
                if name.startswith(prefix) and name.endswith(".glsl"):
                    out = dest / "minecraft" / name[len(prefix):]
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(jar.read(name))
    else:
        base = source / prefix
        for path in base.rglob("*.glsl"):
            out = dest / "minecraft" / path.relative_to(base)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, out)


def rewrite_includes(text: str) -> str:
    """Turn #include <ns:path> into a relative path glslc can resolve on any OS.

    Lines are rewritten one for one, so glslc's line numbers stay correct."""
    out = []
    for line in text.splitlines():
        m = INCLUDE_RE.match(line)
        out.append(f'{m.group(1)}<{m.group(2)}/{m.group(3)}>{m.group(4)}' if m else line)
    return "\n".join(out) + "\n"


def shader_id(rel: Path) -> str:
    """assets/minecraft/shaders/core/text.vsh -> minecraft:core/text"""
    parts = rel.parts
    return f"{parts[1]}:{'/'.join(parts[3:])[: -len(rel.suffix)]}"


def variant_sets(spec: dict, table: dict) -> list[dict[str, str]]:
    flags = spec.get("flags", [])
    values = spec.get("values", {})
    oit_modes: list[dict[str, str]] = [{}]
    if spec.get("oit"):
        for stage in table["oit_stages"].values():
            oit_modes.append({**table["oit_base"], **stage})
    device = [{}, {m: "" for m in table["device_macros"]}]
    value_choices = [[(k, v) for v in opts] for k, opts in values.items()]

    sets = []
    for n in range(len(flags) + 1):
        for chosen in itertools.combinations(flags, n):
            for picks in itertools.product(*value_choices):
                for oit in oit_modes:
                    for dev in device:
                        d = {f: "" for f in chosen}
                        d.update({k: v for k, v in picks if v is not None})
                        d.update(oit)
                        d.update(dev)
                        sets.append(d)
    return sets


def compile_one(glslc: str, src: Path, stage: str, inc: Path, defines: dict[str, str]):
    args = [glslc, f"-fshader-stage={stage}", *GLSLC_ARGS, "-I", str(inc)]
    args += [f"-D{k}={v}" if v else f"-D{k}" for k, v in sorted(defines.items())]
    args += [str(src), "-o", os.devnull]
    proc = subprocess.run(args, capture_output=True, text=True)
    return proc.returncode, (proc.stderr or proc.stdout).strip()


def check_shaders(files: list[Path], vanilla_arg: str | None) -> list[str]:
    shaders = [f for f in files if len(f.parts) > 3 and f.parts[2] == "shaders" and f.parts[3] != "include"
               and f.suffix in STAGES]
    if not shaders:
        return []
    glslc = shutil.which("glslc")
    if not glslc:
        raise BuildError("glslc not found: install shaderc (Vulkan SDK or your distro's shaderc/glslc package)")
    vanilla = find_vanilla(vanilla_arg)
    if vanilla is None:
        raise BuildError(
            f"vanilla {MC_VERSION} shaders not found: pass --vanilla <client jar or extracted dir> "
            "or set MC_VANILLA"
        )
    table = load_json(VARIANTS)
    errors: list[str] = []
    jobs = []
    with tempfile.TemporaryDirectory(prefix="wlpack-") as tmp:
        tmp = Path(tmp)
        inc = tmp / "include"
        stage_vanilla_includes(vanilla, inc)
        # Pack includes override vanilla ones with the same id.
        for rel in files:
            if len(rel.parts) > 4 and rel.parts[2:4] == ("shaders", "include") and rel.suffix == ".glsl":
                out = inc / rel.parts[1] / Path(*rel.parts[4:])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(rewrite_includes((PACK / rel).read_text(encoding="utf-8")), encoding="utf-8")
        for incfile in inc.rglob("*.glsl"):
            incfile.write_text(rewrite_includes(incfile.read_text(encoding="utf-8")), encoding="utf-8")

        for rel in shaders:
            sid = shader_id(rel)
            spec = table["shaders"].get(sid)
            if spec is None:
                if sid.startswith("minecraft:core/"):
                    errors.append(f"{rel}: {sid} has no entry in tools/shader_variants.json; add its defines")
                    continue
                spec = {}
            staged = tmp / "src" / rel
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_text(rewrite_includes((PACK / rel).read_text(encoding="utf-8")), encoding="utf-8")
            for defines in variant_sets(spec, table):
                jobs.append((rel, staged, STAGES[rel.suffix], defines))

        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
            futures = {pool.submit(compile_one, glslc, staged, stage, inc, d): (rel, d)
                       for rel, staged, stage, d in jobs}
            failed: dict[Path, tuple[dict, str]] = {}
            for fut in concurrent.futures.as_completed(futures):
                rel, d = futures[fut]
                code, msg = fut.result()
                # Report the failing variant with the fewest defines: easiest to reproduce.
                if code != 0 and (rel not in failed or len(d) < len(failed[rel][0])):
                    failed[rel] = (d, msg.replace(str(tmp / "src") + os.sep, "pack/").replace(str(tmp), "<staged>"))
        for rel, (d, msg) in sorted(failed.items()):
            shown = " ".join(f"{k}={v}" if v else k for k, v in sorted(d.items())) or "(no defines)"
            errors.append(f"{rel}: fails with {shown}\n{msg}")
    print(f"shaders: {len(shaders)} file(s), {len(jobs)} compile(s), {len(errors)} error(s)")
    return errors


# ---------------------------------------------------------------- build


def content_hash(files: list[Path]) -> str:
    h = hashlib.sha1()
    for rel in files:
        h.update(rel.as_posix().encode() + b"\0")
        h.update((PACK / rel).read_bytes() + b"\0")
    return h.hexdigest()[:12]


def build_zip(files: list[Path], meta: dict) -> tuple[Path, str]:
    stamp = content_hash(files)
    meta = json.loads(json.dumps(meta))
    desc = meta["pack"]["description"]
    if isinstance(desc, str):
        meta["pack"]["description"] = f"{desc} [{stamp}]"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            data = (PACK / rel).read_bytes()
            if rel.as_posix() == "pack.mcmeta":
                data = (json.dumps(meta, indent=2) + "\n").encode()
            info = zipfile.ZipInfo(rel.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    BUILD.mkdir(exist_ok=True)
    out = BUILD / f"{ZIP_PREFIX}{stamp}.zip"
    out.write_bytes(buf.getvalue())
    return out, hashlib.sha1(buf.getvalue()).hexdigest()


# ---------------------------------------------------------------- publish


def git(*args: str, env: dict | None = None, check: bool = True, input: bytes | None = None) -> str:
    proc = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, env=env, input=input)
    if check and proc.returncode != 0:
        raise BuildError(f"git {' '.join(args)} failed:\n{proc.stderr.decode().strip()}")
    return proc.stdout.decode().strip()


def is_ancestor(a: str, b: str) -> bool:
    return subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", a, b]).returncode == 0


def repo_slug(explicit: str | None) -> str:
    if explicit:
        return explicit
    url = git("remote", "get-url", "origin")
    m = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?/?$", url)
    if not m:
        raise BuildError(f"origin is not a GitHub URL ({url}); pass --repo owner/name")
    return f"{m.group(1)}/{m.group(2)}"


def publish(zip_path: Path, sha1: str, slug: str, push: bool) -> str:
    url = f"https://raw.githubusercontent.com/{slug}/{DIST_BRANCH}/{zip_path.name}"
    git("fetch", "origin", DIST_BRANCH, check=False)
    parent = git("rev-parse", "--verify", "-q", f"refs/remotes/origin/{DIST_BRANCH}", check=False)
    local = git("rev-parse", "--verify", "-q", f"refs/heads/{DIST_BRANCH}", check=False)
    if local and parent and local != parent:
        if is_ancestor(parent, local):
            parent = local  # local commits not pushed yet: build on them
        elif not is_ancestor(local, parent):
            raise BuildError(f"local {DIST_BRANCH} and origin/{DIST_BRANCH} have diverged; fix that first")
    parent = parent or local

    with tempfile.TemporaryDirectory(prefix="wlpack-index-") as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        if parent:
            git("read-tree", parent, env=env)
            if git("ls-files", zip_path.name, env=env):
                print(f"already on {DIST_BRANCH}: {zip_path.name}")
                return url
        else:
            git("read-tree", "--empty", env=env)
            readme = (
                f"# {DIST_BRANCH}\n\nBuilt resource packs only, written by tools/build_pack.py on the\n"
                "work branches. Never edit by hand. `latest.json` names the newest pack.\n"
            ).encode()
            blob = git("hash-object", "-w", "--stdin", input=readme)
            git("update-index", "--add", "--cacheinfo", f"100644,{blob},README.md", env=env)

        blob = git("hash-object", "-w", str(zip_path))
        git("update-index", "--add", "--cacheinfo", f"100644,{blob},{zip_path.name}", env=env)
        latest = json.dumps({"file": zip_path.name, "sha1": sha1, "url": url}, indent=2) + "\n"
        blob = git("hash-object", "-w", "--stdin", input=latest.encode())
        git("update-index", "--add", "--cacheinfo", f"100644,{blob},latest.json", env=env)
        tree = git("write-tree", env=env)

    source = git("rev-parse", "--short", "HEAD", check=False) or "unknown"
    args = ["commit-tree", tree, "-m", f"Publish {zip_path.name} (built from {source})"]
    if parent:
        args += ["-p", parent]
    commit = git(*args)
    git("update-ref", f"refs/heads/{DIST_BRANCH}", commit)
    print(f"committed {zip_path.name} to {DIST_BRANCH} ({commit[:10]})")
    if push:
        git("push", "origin", DIST_BRANCH)
        print(f"pushed {DIST_BRANCH}")
    else:
        print(f"not pushed: run `git push origin {DIST_BRANCH}`")
    return url


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="validate only, write nothing")
    ap.add_argument("--publish", action="store_true", help=f"commit the built zip to the {DIST_BRANCH} branch")
    ap.add_argument("--push", action="store_true", help=f"with --publish: push {DIST_BRANCH} to origin")
    ap.add_argument("--vanilla", help=f"{MC_VERSION} client jar or extracted dir with assets/minecraft/shaders")
    ap.add_argument("--repo", help="GitHub owner/name for the raw URL (default: from origin)")
    args = ap.parse_args()

    try:
        meta = check_mcmeta()
        files = pack_files()
        errors = check_files(files) + check_shaders(files, args.vanilla)
        if errors:
            print("\n".join(f"error: {e}" for e in errors), file=sys.stderr)
            print(f"{len(errors)} error(s)", file=sys.stderr)
            return 1
        print(f"valid: {len(files)} file(s)")
        if args.check:
            return 0
        zip_path, sha1 = build_zip(files, meta)
        print(f"built {zip_path.relative_to(ROOT)} ({zip_path.stat().st_size} bytes, sha1 {sha1})")
        if args.publish:
            url = publish(zip_path, sha1, repo_slug(args.repo), args.push)
            print(f"url: {url}")
        return 0
    except BuildError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
