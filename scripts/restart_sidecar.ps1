# Stop the sidecar CHILD on port 8788; its supervisor starts it again on the
# current code. Only safe with the WAL folded (check graph.kuzu.wal first).
$c = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='python3.13.exe'" | Where-Object { $_.CommandLine -match 'domvec.obsidian serve' -and $_.CommandLine -match '8788' }
$c | ForEach-Object { "stopping $($_.ProcessId) (started $($_.CreationDate))"; Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
