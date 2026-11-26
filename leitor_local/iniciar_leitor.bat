@echo off
REM Liga o leitor do Messenger (deixe esta janela aberta/minimizada)
cd /d "%~dp0"
start "Leitor Messenger" /min cmd /k python leitor_messenger.py
echo Leitor iniciado (janela minimizada "Leitor Messenger").
echo Para iniciar junto com o Windows: Win+R, shell:startup, e coloque
echo um atalho deste arquivo nessa pasta.
timeout /t 8
