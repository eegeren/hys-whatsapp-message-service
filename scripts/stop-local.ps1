$root=Split-Path $PSScriptRoot -Parent
$all=Get-CimInstance Win32_Process
# Windows venv python.exe may launch the base interpreter as a child.
# Select only this workspace's venv launcher and its HYS Python children.
$owned=@($all | Where-Object { $_.ExecutablePath -eq "$root\.venv\Scripts\python.exe" -and $_.CommandLine -match 'app.main:app|app.worker' })
foreach($launcher in $owned){
  foreach($child in @($all | Where-Object { $_.ParentProcessId -eq $launcher.ProcessId -and $_.Name -eq 'python.exe' -and $_.CommandLine -match 'app.main:app|app.worker' })){
    Stop-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
  }
  Stop-Process -Id $launcher.ProcessId -ErrorAction SilentlyContinue
}
if(Test-Path -LiteralPath "$root\.local-pids.json"){
  $ids=Get-Content -LiteralPath "$root\.local-pids.json" -Raw | ConvertFrom-Json
  foreach($processId in @($ids.api,$ids.worker)){
    $p=Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
    if($p -and $p.ExecutablePath -eq "$root\.venv\Scripts\python.exe" -and ($p.CommandLine -match 'app.main:app|app.worker')){Stop-Process -Id $processId -ErrorAction SilentlyContinue}
  }
  Remove-Item -LiteralPath "$root\.local-pids.json"
}
Write-Host 'Yerel islemler durduruldu; veritabani korundu.'
