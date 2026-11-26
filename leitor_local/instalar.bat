@echo off
REM Instalacao manual (antiga). Prefira o INSTALAR.bat, que faz tudo sozinho.
cd /d "%~dp0"
python -m pip install --upgrade playwright
python -m playwright install chromium
echo.
echo Pronto. Agora preencha a secao [servidor] do config.ini
echo e rode o login_messenger.bat.
pause
