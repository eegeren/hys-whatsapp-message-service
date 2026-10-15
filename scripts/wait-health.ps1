$ErrorActionPreference='Stop'
for ($i=0;$i -lt 90;$i++) {
    try { $health=Invoke-RestMethod http://localhost:3000/api/health; if($health.ok){exit 0} } catch {}
    Start-Sleep -Seconds 2
}
Write-Error 'API zamaninda hazir olmadi. docker compose logs api ile kontrol edin.'
exit 1
