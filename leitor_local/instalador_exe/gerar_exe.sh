#!/bin/sh
# Gera leitor_local/dist/InstalarLeitorMessenger.exe (precisa do Go 1.21+).
# Rode de novo sempre que mudar algum arquivo da pasta leitor_local.
set -e
cd "$(dirname "$0")"
rm -rf payload && mkdir payload
for f in instalador.ps1 leitor_messenger.py config.ini iniciar_leitor.bat login_messenger.bat "COMO INSTALAR.txt"; do
    cp "../$f" payload/
done
mkdir -p ../dist
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o ../dist/InstalarLeitorMessenger.exe .
rm -rf payload
echo "OK: leitor_local/dist/InstalarLeitorMessenger.exe"
