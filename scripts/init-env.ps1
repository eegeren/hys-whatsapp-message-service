$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
if (Test-Path -LiteralPath "$root\.env") { exit 0 }
$password = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')
$bootstrap = [Guid]::NewGuid().ToString('N')
$content = (Get-Content -LiteralPath "$root\.env.example" -Raw).Replace('CHANGE_ME_TO_A_LONG_RANDOM_PASSWORD', $password).Replace('BOOTSTRAP_TOKEN=', "BOOTSTRAP_TOKEN=$bootstrap")
[IO.File]::WriteAllText("$root\.env", $content, [Text.UTF8Encoding]::new($false))
Write-Host 'Ilk kurulum anahtari .env dosyasindaki BOOTSTRAP_TOKEN alanindadir.'
