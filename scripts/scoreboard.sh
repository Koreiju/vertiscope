#!/usr/bin/env bash
# One run of the PRD scoreboard, live rows included.
#
# The sequence is not decoration. kuzu takes an EXCLUSIVE lock, so the sidecar
# and the offline measurement cannot hold the workspace at the same time --
# and the live rows need the sidecar, because the 3D view fetches its layout
# from it. So: probe while it is up, stop it, measure, put it back.
set -u
cd "$(dirname "$0")/.."
LIVE="${TMPDIR:-/tmp}/vertiscope-live.json"

echo "== live probe (Obsidian must be running with --remote-debugging-port=9222)"
( cd obsidian-plugin && node cdp.mjs --file probes/scoreboard-live.js ) > "$LIVE" 2>/dev/null \
  && echo "   ok" || echo "   unavailable -- live rows will read '-'"

echo "== stopping the sidecar"
powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | Where-Object { \$_.CommandLine -like '*vertiscope.obsidian serve*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" >/dev/null 2>&1
sleep 3

python scripts/scoreboard.py --workspace build/vaultws512 --live-from "$LIVE" "$@"
CODE=$?

echo "== restarting the sidecar"
powershell.exe -NoProfile -Command "Set-Location '<home>\Documents\vertiscope'; Start-Process -FilePath 'python' -ArgumentList '-u','-m','vertiscope.obsidian','serve','--workspace','build/vaultws512','--port','8788' -WindowStyle Hidden" >/dev/null 2>&1
exit $CODE
