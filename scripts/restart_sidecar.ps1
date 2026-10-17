# Stop the sidecar CHILD on port 8788; its supervisor starts it again on the
# current code. Refused while a CHECKPOINT runs (the WAL reads ~0 bytes during
# one, and two restarts on 2026-10-17 killed the fold mid-way), while the
# sidecar cannot answer (busy is treated as checkpointing), or with the WAL
# over 8 MB. -Force overrides.
param([switch]$Force)
if (-not $Force) {
  try { $cp = Invoke-RestMethod -TimeoutSec 5 http://127.0.0.1:8788/checkpointing } catch { "refused: the sidecar did not answer /checkpointing (busy?)"; exit 1 }
  if ($cp.checkpointing) { "refused: a checkpoint is running"; exit 1 }
  $wal = Get-Item "$PSScriptRoot\..\build\corpus123\graph.kuzu.wal" -ErrorAction SilentlyContinue
  if ($wal -and $wal.Length -gt 8MB) { "refused: WAL is $([math]::Round($wal.Length/1MB,1)) MB"; exit 1 }
}
$c = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='python3.13.exe'" | Where-Object { $_.CommandLine -match 'domvec.obsidian serve' -and $_.CommandLine -match '8788' }
$c | ForEach-Object { "stopping $($_.ProcessId) (started $($_.CreationDate))"; Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
