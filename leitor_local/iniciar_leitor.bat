@echo off
REM Liga o leitor do Messenger (deixe esta janela aberta/minimizada)
REM O INSTALAR.bat ja faz ele ligar sozinho junto com o Windows.
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
start "Leitor Messenger" /min cmd /k %PY% leitor_messenger.py
echo Leitor iniciado (janela minimizada "Leitor Messenger").
timeout /t 8
