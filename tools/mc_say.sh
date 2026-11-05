#!/bin/sh
# Type a chat line into the running Minecraft window (for testing on the plot).
#   tools/mc_say.sh "@wl test"
WIN=$(wmctrl -lx | awk '$3 ~ /mojang.minecraft/ {print $1; exit}')
[ -z "$WIN" ] && WIN=$(xdotool search --name "^Minecraft" | head -1)
[ -z "$WIN" ] && { echo "no Minecraft window"; exit 2; }
xdotool windowactivate "$WIN" 2>/dev/null
sleep 0.3
xdotool key t
sleep 0.3
xdotool type --delay 25 "$1"
sleep 0.1
xdotool key Return
