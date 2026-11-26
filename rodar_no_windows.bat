@echo off
REM Roda o painel web NESTE PC (teste ou servidor Windows da rede)
cd /d "%~dp0"
python -m pip install -r requirements.txt >nul
echo Painel: http://localhost:5000   Admin: http://localhost:5000/admin
echo A senha inicial do admin aparece abaixo e em dados\SENHA_INICIAL_ADMIN.txt
python app.py
pause
