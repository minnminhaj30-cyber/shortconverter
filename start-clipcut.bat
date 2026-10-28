@echo off
set "ROOT=%~dp0"
start "ClipCut Backend" powershell -NoExit -Command "& { Set-Location -LiteralPath '%ROOT%backend\backend'; & '..\clipvenv\Scripts\python.exe' manage.py migrate --noinput; if ($LASTEXITCODE -eq 0) { & '..\clipvenv\Scripts\python.exe' manage.py runserver 127.0.0.1:8000 } }"

for /L %%I in (1,1,30) do (
  powershell -NoProfile -NonInteractive -Command "try { Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/api/jobs/' -TimeoutSec 1 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
  if not errorlevel 1 goto backend_ready
  timeout /t 1 /nobreak >nul
)

echo ClipCut backend did not start. Check the ClipCut Backend window for errors.
pause
exit /b 1

:backend_ready
start "ClipCut Frontend" powershell -NoExit -Command "& { Set-Location -LiteralPath '%ROOT%frontend\frontend'; npm run dev }"
