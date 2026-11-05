#!/bin/sh
# Compile, place the code on the plot and switch to play mode.
S=$HOME/.claude/skills/terracotta/scripts
"$S/tc-send.py" "$(dirname "$0")/.." "$@" 2>&1 | tail -2 && "$S/tc-mode.py" play 2>&1 | tail -1
