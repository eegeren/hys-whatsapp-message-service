$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
if(Test-Path .local-pids.json){
  $old=Get-Content .local-pids.json -Raw | ConvertFrom-Json
  if(Get-Process -Id $old.api -ErrorAction SilentlyContinue){Write-Host 'Yerel API zaten calisiyor: http://localhost:3000';exit 0}
}
if(-not(Test-Path .venv\Scripts\python.exe)){python -m venv .venv;if($LASTEXITCODE){exit 1}}
& .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if($LASTEXITCODE){exit 1}
Push-Location frontend
& npm.cmd ci
if($LASTEXITCODE){Pop-Location;exit 1}
& npm.cmd run build
if($LASTEXITCODE){Pop-Location;exit 1}
Pop-Location
$env:DATABASE_URL='sqlite:///'+($root.Replace('\','/')+'/hys-local.db')
$env:DRY_RUN='true'
$env:LIVE_SEND_ENABLED='false'
$env:LOCAL_WORKER='true'
Push-Location backend
& ..\.venv\Scripts\python.exe -m alembic upgrade head
if($LASTEXITCODE){Pop-Location;exit 1}
Pop-Location
$api=Start-Process -FilePath "$root\.venv\Scripts\python.exe" -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','3000','--no-access-log' -WorkingDirectory "$root\backend" -WindowStyle Hidden -PassThru -RedirectStandardOutput "$root\api.log" -RedirectStandardError "$root\api-error.log"
$worker=Start-Process -FilePath "$root\.venv\Scripts\python.exe" -ArgumentList '-m','app.worker' -WorkingDirectory "$root\backend" -WindowStyle Hidden -PassThru -RedirectStandardOutput "$root\worker.log" -RedirectStandardError "$root\worker-error.log"
@{api=$api.Id;worker=$worker.Id} | ConvertTo-Json | Set-Content .local-pids.json
& "$PSScriptRoot\wait-health.ps1"
if($LASTEXITCODE){exit 1}
Write-Host 'Yerel DRY_RUN paneli: http://localhost:3000 (SQLite; Docker surumu PostgreSQL + Redis + Celery)'
Start-Process http://localhost:3000
