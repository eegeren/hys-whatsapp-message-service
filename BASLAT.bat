@echo off
chcp 65001 >nul
cd /d "%~dp0"
where docker >nul 2>nul
if errorlevel 1 (
 echo Docker bulunamadi. Docker Desktop kurup Linux containers modunda baslatin.
 echo Yerel DRY_RUN icin BASLAT_YEREL.bat kullanabilirsiniz.
 pause
 exit /b 1
)
if not exist .env powershell -NoProfile -ExecutionPolicy Bypass -File scripts\init-env.ps1
docker compose up -d --build
if errorlevel 1 (
 echo Baslatma basarisiz. Docker Desktop ve .env dosyasini kontrol edin.
 pause
 exit /b 1
)
echo Panel hazirlaniyor: http://localhost:3000
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\wait-health.ps1
if errorlevel 1 exit /b 1
start "" http://localhost:3000
