#!/bin/sh
# Print the Minecraft client's receive rate from the DiamondFire server, once a
# second for $1 seconds (default 12), from the kernel's TCP counters (ss -ti).
recv() { ss -tin 'dport = :25565' | grep -o 'bytes_received:[0-9]*' | cut -d: -f2 | sort -n | tail -1; }
prev=$(recv)
for i in $(seq 1 "${1:-12}"); do
    sleep 1
    now=$(recv)
    echo "$(( (now - prev) / 1024 )) KB/s"
    prev=$now
done
