$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
New-Item -ItemType Directory -Force backups | Out-Null
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$container=$null
if(Get-Command docker -ErrorAction SilentlyContinue){$container=docker compose ps -q --status running postgres 2>$null}
if($container){
  docker compose exec -T postgres pg_dump -U hys -d hys -Fc -f /tmp/hys.dump
  if($LASTEXITCODE){exit 1}
  docker cp "${container}:/tmp/hys.dump" "backups\hys-$stamp.dump"
}elseif(Test-Path hys-local.db){
  & .\.venv\Scripts\python.exe scripts\backup-local.py "backups\hys-$stamp.sqlite"
}else{
  Write-Error 'Calisan PostgreSQL servisi veya yerel veritabani bulunamadi.'
  exit 1
}
Write-Host 'Yedek backups klasorune alindi. Kisisel veri icerir; erisimi sinirlayin.'
