@echo off
REM ============================================================
REM  INSTALADOR DO LEITOR DO MESSENGER - de dois cliques aqui.
REM  Ele instala tudo, pede o token do painel e liga o leitor.
REM ============================================================
cd /d "%~dp0"
title Instalador do Leitor do Messenger
if not exist "%~dp0instalador.ps1" (
    echo.
    echo  Nao achei o arquivo instalador.ps1.
    echo  Extraia o .zip inteiro primeiro: botao direito no .zip,
    echo  "Extrair tudo", e rode o INSTALAR.bat de dentro da pasta extraida.
    echo.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalador.ps1" %*
echo.
pause
