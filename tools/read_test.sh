#!/bin/sh
# Print the latest WLTEST run (tests.tc) from the Minecraft client log.
# Waits up to $1 seconds (default 30) for a new "WLTEST DONE" line.
# Exit 0 = no failures, 1 = failures, 2 = no new run.
LOG=$HOME/.var/app/org.prismlauncher.PrismLauncher/data/PrismLauncher/instances/26.3/minecraft/logs/latest.log
lines() { grep -a 'WLTEST' "$LOG" 2>/dev/null | sed 's/.*\[CHAT\] //'; }
before=${BEFORE:-$(lines | grep -c 'WLTEST DONE')}
for i in $(seq 1 "${1:-30}"); do
    [ "$(lines | grep -c 'WLTEST DONE')" -gt "$before" ] && break
    sleep 1
done
[ "$(lines | grep -c 'WLTEST DONE')" -le "$before" ] && { echo "no new WLTEST run"; exit 2; }
out=$(lines)
start=$(printf '%s\n' "$out" | grep -n 'WLTEST BEGIN' | tail -1 | cut -d: -f1)
printf '%s\n' "$out" | tail -n +"$start"
printf '%s\n' "$out" | tail -n +"$start" | grep -q 'WLTEST FAIL' && exit 1
exit 0
