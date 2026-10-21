# Restart the sidecar CHILD on port 8788 GRACEFULLY: POST /shutdown makes it
# refuse new writes, wait for the work lock (every capture, embed batch,
# settle and checkpoint in flight finishes), then exit; its supervisor starts
# it again on the current code. A kill interrupted a capture's transaction
# on 2026-10-17 (19:35) and two checkpoints before that. -Force kills
# (only for a sidecar too old to have /shutdown, after checking it is idle).
param([switch]$Force)
if (-not $Force) {
  try { $r = Invoke-RestMethod -Method Post -TimeoutSec 10 http://127.0.0.1:8788/shutdown } catch { "refused: /shutdown did not answer"; exit 1 }
  "asked to shut down: $($r | ConvertTo-Json -Compress)"
  exit 0
}
$c = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='python3.13.exe'" | Where-Object { $_.CommandLine -match 'vertiscope.obsidian serve' -and $_.CommandLine -match '8788' }
$c | ForEach-Object { "stopping $($_.ProcessId) (started $($_.CreationDate))"; Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
