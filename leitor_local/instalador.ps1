# ============================================================
# INSTALADOR DO LEITOR DO MESSENGER (PC do escritório, Windows)
# Não rode este arquivo direto: dê dois cliques em INSTALAR.bat.
#
# O que ele faz, sozinho:
#   1. copia o leitor para  %USERPROFILE%\LeitorMessenger
#   2. instala o Python (se faltar) e o Playwright num ambiente próprio
#   3. confere se o Google Chrome está instalado
#   4. pede o TOKEN (Admin -> Atendimento), testa e grava no config.ini
#   5. faz o leitor ligar junto com o Windows e cria atalhos na Área de Trabalho
#   6. abre o login do Messenger (só na primeira vez)
# Pode rodar de novo quantas vezes quiser: ele só atualiza o que precisa.
# ============================================================

param(
    [string]$Url = "",
    [string]$Token = ""
)

$ErrorActionPreference = "Stop"
$URL_PADRAO = "https://painelcorporativo.pythonanywhere.com"
$PYTHON_INSTALADOR = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName Microsoft.VisualBasic
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$ORIGEM = Split-Path -Parent $MyInvocation.MyCommand.Path
$DESTINO = Join-Path $env:USERPROFILE "LeitorMessenger"
$TITULO = "Instalador do Leitor do Messenger"

function Passo($texto) { Write-Host ""; Write-Host "==> $texto" -ForegroundColor Cyan }
function Ok($texto) { Write-Host "    OK: $texto" -ForegroundColor Green }
function Aviso($texto) { Write-Host "    ATENCAO: $texto" -ForegroundColor Yellow }

function Mensagem($texto, $icone = "Information", $botoes = "OK") {
    return [System.Windows.Forms.MessageBox]::Show($texto, $TITULO, $botoes, $icone)
}

function Falhar($texto) {
    Write-Host ""
    Write-Host "ERRO: $texto" -ForegroundColor Red
    Mensagem "$texto`n`nTire um print desta mensagem e da janela preta e envie para o suporte." "Error" | Out-Null
    exit 1
}

function Atualizar-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Tem-Winget { return [bool](Get-Command winget -ErrorAction SilentlyContinue) }

# ------------------------------------------------------------
# config.ini: ler e gravar a seção [servidor] sem mexer no resto
# ------------------------------------------------------------
function Ler-Servidor($arquivo, $chave) {
    if (-not (Test-Path $arquivo)) { return "" }
    $secao = ""
    foreach ($linha in [IO.File]::ReadAllLines($arquivo)) {
        $t = $linha.Trim()
        if ($t -match '^\[(.+)\]$') { $secao = $Matches[1].Trim().ToLower(); continue }
        if ($secao -eq "servidor" -and $t -match "^$chave\s*=\s*(.*)$") { return $Matches[1].Trim() }
    }
    return ""
}

function Gravar-Servidor($arquivo, $url, $token) {
    $linhas = [Collections.Generic.List[string]]([IO.File]::ReadAllLines($arquivo))
    $secao = ""; $achouUrl = $false; $achouToken = $false; $fimServidor = -1
    for ($i = 0; $i -lt $linhas.Count; $i++) {
        $t = $linhas[$i].Trim()
        if ($t -match '^\[(.+)\]$') {
            if ($secao -eq "servidor" -and $fimServidor -lt 0) { $fimServidor = $i }
            $secao = $Matches[1].Trim().ToLower(); continue
        }
        if ($secao -eq "servidor") {
            if ($t -match '^url\s*=') { $linhas[$i] = "url   = $url"; $achouUrl = $true }
            elseif ($t -match '^token\s*=') { $linhas[$i] = "token = $token"; $achouToken = $true }
        }
    }
    if ($secao -eq "servidor" -and $fimServidor -lt 0) { $fimServidor = $linhas.Count }
    if (-not ($achouUrl -and $achouToken)) {
        if ($fimServidor -lt 0) { $linhas.Add(""); $linhas.Add("[servidor]"); $fimServidor = $linhas.Count }
        if (-not $achouToken) { $linhas.Insert($fimServidor, "token = $token") }
        if (-not $achouUrl) { $linhas.Insert($fimServidor, "url   = $url") }
    }
    [IO.File]::WriteAllLines($arquivo, $linhas, (New-Object Text.UTF8Encoding($true)))
}

function Testar-Token($url, $token) {
    # "ok" | "invalido" | "antigo" (servidor sem a rota de teste) | "sem_conexao"
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "$url/api/atendimento/verificar" -TimeoutSec 20 `
             -Headers @{ Authorization = "Bearer $token" }
        if ($r.StatusCode -eq 200) { return "ok" }
    } catch {
        $codigo = 0
        if ($_.Exception.Response) { $codigo = [int]$_.Exception.Response.StatusCode }
        if ($codigo -eq 401) { return "invalido" }
        if ($codigo -eq 404 -or $codigo -eq 405) { return "antigo" }
        return "sem_conexao"
    }
    return "sem_conexao"
}

# ------------------------------------------------------------
# Python
# ------------------------------------------------------------
function Python-Serve($exe, $argsExtra) {
    try {
        $saida = & $exe @argsExtra -c "import sys; print(sys.version_info >= (3, 9))" 2>$null
        return ($LASTEXITCODE -eq 0 -and "$saida".Trim() -eq "True")
    } catch { return $false }
}

function Achar-Python {
    $candidatos = @(
        @{ exe = "py"; args = @("-3") },
        @{ exe = "python"; args = @() }
    )
    foreach ($v in "313", "312", "311", "310", "39") {
        foreach ($base in $env:LOCALAPPDATA, $env:ProgramFiles) {
            if ($base) { $candidatos += @{ exe = (Join-Path $base "Programs\Python\Python$v\python.exe"); args = @() } }
            if ($base) { $candidatos += @{ exe = (Join-Path $base "Python$v\python.exe"); args = @() } }
        }
    }
    foreach ($c in $candidatos) {
        if ((Get-Command $c.exe -ErrorAction SilentlyContinue) -and (Python-Serve $c.exe $c.args)) { return $c }
    }
    return $null
}

function Instalar-Python {
    if (Tem-Winget) {
        Write-Host "    Instalando o Python pelo winget (pode demorar alguns minutos)..."
        & winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Host
        Atualizar-Path
        $py = Achar-Python
        if ($py) { return $py }
    }
    Write-Host "    Baixando o Python do site oficial (python.org)..."
    $arq = Join-Path $env:TEMP "python-instalador.exe"
    Invoke-WebRequest -UseBasicParsing -Uri $PYTHON_INSTALADOR -OutFile $arq
    Write-Host "    Instalando o Python (pode demorar alguns minutos)..."
    $p = Start-Process -FilePath $arq -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0" -Wait -PassThru
    Remove-Item $arq -ErrorAction SilentlyContinue
    if ($p.ExitCode -ne 0) { Falhar "A instalação do Python falhou (código $($p.ExitCode))." }
    Atualizar-Path
    return Achar-Python
}

# ------------------------------------------------------------
# Chrome
# ------------------------------------------------------------
function Achar-Chrome {
    foreach ($base in $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA) {
        if (-not $base) { continue }
        $c = Join-Path $base "Google\Chrome\Application\chrome.exe"
        if (Test-Path $c) { return $c }
    }
    return $null
}

# ------------------------------------------------------------
# Atalhos
# ------------------------------------------------------------
function Criar-Atalho($caminho, $alvo, $pasta, $descricao, $janela = 1) {
    $shell = New-Object -ComObject WScript.Shell
    $a = $shell.CreateShortcut($caminho)
    $a.TargetPath = $alvo
    $a.WorkingDirectory = $pasta
    $a.Description = $descricao
    $a.WindowStyle = $janela   # 1 = normal, 7 = minimizada
    $a.Save()
}

# ============================================================
# INÍCIO
# ============================================================
Clear-Host
Write-Host "============================================================"
Write-Host "  INSTALADOR DO LEITOR DO MESSENGER"
Write-Host "  Instalando em: $DESTINO"
Write-Host "============================================================"

if (-not (Test-Path (Join-Path $ORIGEM "leitor_messenger.py"))) {
    Falhar "Não achei o arquivo leitor_messenger.py ao lado do instalador.`nExtraia o .zip inteiro (botão direito -> Extrair tudo) e rode o INSTALAR.bat de dentro da pasta extraída."
}

# ---------- 1. fecha o leitor antigo e copia os arquivos ----------
Passo "1/6  Copiando os arquivos do leitor"
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*leitor_messenger.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

New-Item -ItemType Directory -Force -Path $DESTINO | Out-Null
$mesmaPasta = ((Resolve-Path $ORIGEM).Path.TrimEnd('\') -ieq (Resolve-Path $DESTINO).Path.TrimEnd('\'))
$configDestino = Join-Path $DESTINO "config.ini"
$configOrigem = Join-Path $ORIGEM "config.ini"

if (-not $mesmaPasta) {
    Get-ChildItem -Path $ORIGEM -File | Where-Object { $_.Name -ne "config.ini" } |
        ForEach-Object { Copy-Item $_.FullName -Destination $DESTINO -Force }
    if (-not (Test-Path $configDestino)) {
        Copy-Item $configOrigem -Destination $configDestino
    }
    # reaproveita o login de uma instalação antiga (pasta perfil_messenger)
    $perfilOrigem = Join-Path $ORIGEM "perfil_messenger"
    $perfilDestino = Join-Path $DESTINO "perfil_messenger"
    if ((Test-Path $perfilOrigem) -and -not (Test-Path $perfilDestino)) {
        Write-Host "    Reaproveitando o login antigo (pasta perfil_messenger)..."
        Copy-Item $perfilOrigem -Destination $perfilDestino -Recurse
    }
}
Ok "arquivos em $DESTINO"

# ---------- 2. Python + Playwright ----------
Passo "2/6  Conferindo o Python"
$py = Achar-Python
if (-not $py) {
    Aviso "Python não encontrado. Vou instalar agora."
    $py = Instalar-Python
    if (-not $py) { Falhar "Não consegui instalar o Python. Instale pelo site python.org (marque 'Add python.exe to PATH') e rode o INSTALAR.bat de novo." }
}
Ok ("Python: " + (& $py.exe @($py.args) --version))

Passo "3/6  Instalando o Playwright (pode demorar alguns minutos)"
$venv = Join-Path $DESTINO ".venv"
$venvPy = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    & $py.exe @($py.args) -m venv $venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPy)) { Falhar "Não consegui criar o ambiente do Python em $venv." }
}
& $venvPy -m pip install --disable-pip-version-check --upgrade pip playwright | Out-Host
if ($LASTEXITCODE -ne 0) { Falhar "A instalação do Playwright falhou. Confira a internet e rode o INSTALAR.bat de novo." }
Ok "Playwright instalado"

# ---------- 3. Chrome ----------
$chrome = Achar-Chrome
if (-not $chrome -and (Tem-Winget)) {
    Aviso "Google Chrome não encontrado. Vou instalar agora."
    & winget install -e --id Google.Chrome --silent --accept-package-agreements --accept-source-agreements | Out-Host
    $chrome = Achar-Chrome
}
if ($chrome) {
    Ok "Google Chrome: $chrome"
} else {
    Aviso "Google Chrome não encontrado. Instalando o navegador reserva do Playwright..."
    & $venvPy -m playwright install chromium | Out-Host
    Mensagem "O Google Chrome não está instalado neste PC.`n`nO login do Messenger precisa do Chrome. Vou abrir a página de download: instale o Chrome e depois rode o INSTALAR.bat de novo." "Warning" | Out-Null
    Start-Process "https://www.google.com/chrome/"
}

# ---------- 4. endereço e token ----------
Passo "4/6  Ligando o leitor ao painel web"
$urlAtual = if ($Url) { $Url } else { Ler-Servidor $configDestino "url" }
if (-not $urlAtual) { $urlAtual = Ler-Servidor $configOrigem "url" }
if (-not $urlAtual) { $urlAtual = $URL_PADRAO }
$urlAtual = $urlAtual.Trim().TrimEnd("/")

$tokenAtual = if ($Token) { $Token } else { Ler-Servidor $configOrigem "token" }
if (-not $tokenAtual) { $tokenAtual = Ler-Servidor $configDestino "token" }

$pedir = -not $tokenAtual
while ($true) {
    if ($pedir) {
        $tokenAtual = [Microsoft.VisualBasic.Interaction]::InputBox(
            "Cole aqui o TOKEN do leitor.`n`nOnde pegar: entre no painel ($urlAtual/admin), abra 'Atendimento', clique no olho ao lado de 'Token do leitor' e depois no botão de copiar.",
            $TITULO, $tokenAtual).Trim()
        if (-not $tokenAtual) { Falhar "Instalação cancelada: o token não foi informado." }
    }
    Write-Host "    Testando o token em $urlAtual ..."
    $resultado = Testar-Token $urlAtual $tokenAtual
    if ($resultado -eq "ok") { Ok "token aceito pelo painel"; break }
    if ($resultado -eq "antigo") { Aviso "o painel ainda não tem a rota de teste; o token será conferido quando o leitor ligar."; break }
    if ($resultado -eq "invalido") {
        Mensagem "O painel recusou este token.`n`nConfira se copiou o token inteiro (Admin -> Atendimento) e tente de novo." "Warning" | Out-Null
        $pedir = $true; continue
    }
    $r = Mensagem "Não consegui falar com $urlAtual.`n`nConfira a internet deste PC.`n`nSim = tentar de novo`nNão = continuar mesmo assim" "Warning" "YesNo"
    if ($r -eq "No") { break }
}
Gravar-Servidor $configDestino $urlAtual $tokenAtual
Ok "config.ini atualizado"

# ---------- 5. atalhos ----------
Passo "5/6  Criando atalhos"
$inicializar = [Environment]::GetFolderPath("Startup")
$areaTrabalho = [Environment]::GetFolderPath("Desktop")
Criar-Atalho (Join-Path $inicializar "Leitor do Messenger.lnk") (Join-Path $DESTINO "iniciar_leitor.bat") $DESTINO "Liga o leitor do Messenger" 7
Criar-Atalho (Join-Path $areaTrabalho "Leitor do Messenger - Ligar.lnk") (Join-Path $DESTINO "iniciar_leitor.bat") $DESTINO "Liga o leitor do Messenger" 7
Criar-Atalho (Join-Path $areaTrabalho "Leitor do Messenger - Fazer login.lnk") (Join-Path $DESTINO "login_messenger.bat") $DESTINO "Login no Onvio (quando a TV pedir)"
Ok "o leitor vai ligar sozinho junto com o Windows"
Ok "atalhos criados na Área de Trabalho"

# ---------- 6. login / ligar ----------
Passo "6/6  Ligando o leitor"
$temLogin = Test-Path (Join-Path $DESTINO "perfil_messenger\Default")
if ($temLogin) {
    Start-Process -FilePath (Join-Path $DESTINO "iniciar_leitor.bat") -WorkingDirectory $DESTINO -WindowStyle Minimized
    Mensagem "Pronto! O leitor do Messenger está instalado e ligado.`n`nEm até 30 segundos o card da TV fica 'AO VIVO'.`n`nSe um dia a TV mostrar 'Login necessário', use o atalho 'Leitor do Messenger - Fazer login' na Área de Trabalho." | Out-Null
} else {
    Mensagem "Falta só o login no Messenger (é feito uma vez).`n`nAo clicar em OK, o Chrome vai abrir:`n  1. entre no Onvio com usuário e senha`n  2. abra o Messenger até aparecer a aba 'Pendentes'`n  3. FECHE o Chrome`n`nDepois disso o leitor liga sozinho." | Out-Null
    Start-Process -FilePath (Join-Path $DESTINO "login_messenger.bat") -WorkingDirectory $DESTINO
}
Write-Host ""
Write-Host "Instalação concluída." -ForegroundColor Green
