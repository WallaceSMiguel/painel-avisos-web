@echo off
REM Faz o login no Messenger UMA vez. A senha NAO fica salva:
REM so a sessao, na pasta "perfil_messenger".
REM Passo a passo: login no Onvio -> abrir o Messenger -> FECHAR o Chrome.
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
REM fecha o leitor, se estiver rodando (ele usa o mesmo perfil do Chrome)
taskkill /FI "WINDOWTITLE eq Leitor Messenger*" /T /F >nul 2>nul
timeout /t 2 /nobreak >nul
%PY% leitor_messenger.py --login
if %errorlevel%==0 (
    echo.
    echo Religando o leitor do Messenger ^(janela minimizada^)...
    start "Leitor Messenger" /min cmd /k %PY% leitor_messenger.py
    echo Pronto! Em ate 30 segundos o card da TV fica "AO VIVO".
    echo O card da TV no painel web atualiza sozinho.
)
pause
