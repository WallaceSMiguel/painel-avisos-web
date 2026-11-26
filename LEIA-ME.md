# Painel de Avisos · Valorização (versão web)

Painel da TV (avisos, agenda das salas e atendimento do Messenger) + painel do administrador, tudo pelo navegador.

| Endereço | Para quê |
|---|---|
| `https://SEU-DOMINIO/` | Tela da TV |
| `https://SEU-DOMINIO/admin` | Painel do administrador |
| `https://SEU-DOMINIO/?debug=1` | Diagnóstico de vídeo na TV |

## O que o administrador faz pelo painel

- **Avisos:** arraste imagens ou vídeos (vários de uma vez). Uma imagem entra no ar assim que termina de enviar. Um vídeo é ajustado automaticamente para a TV (1080p, H.264, faststart, como fazia o `converter_videos.bat`) e entra no ar quando o ajuste termina. A barra de progresso mostra cada etapa.
- Em cada aviso dá para pôr título e texto, escolher **Carrossel** ou **Destaque**, definir o tempo na tela, programar quando ele entra e sai do ar, pausar e mudar a ordem (é só arrastar).
- **Agenda das salas:** envie a planilha `.xlsx`. A aba **Salas** da planilha antiga funciona sem mudar nada. A TV atualiza em até 4 segundos. Tem um botão para baixar o modelo e outro para baixar a planilha atual.
- **Atendimento:** mostra o status do leitor do Messenger e quem está aguardando. Também liga e desliga o card na TV.
- **Configurações:** textos do topo e do rodapé, tempo padrão das imagens, chave de acesso da TV, usuários, troca de senha e histórico de alterações.

## Como funciona o Messenger agora

O login no Onvio precisa de uma pessoa e de um Chrome de verdade. Por isso o **leitor continua no PC do escritório** e só **envia** os dados para o servidor:

```
PC do escritório (leitor_local)  ──HTTPS + token──▶  Servidor web  ──▶  TVs
```

### Instalar o leitor (jeito fácil, Windows)

1. No admin, abra **Atendimento** e clique em **Baixar instalador do leitor**. O `LeitorMessenger.zip` já vem com o endereço e o token do painel.
2. No PC do escritório, clique com o botão direito no zip e escolha **Extrair tudo**.
3. Dê dois cliques em **`INSTALAR.bat`**. Se aparecer "O Windows protegeu o computador", clique em **Mais informações** e depois em **Executar assim mesmo**.
4. Na primeira vez o Chrome abre sozinho: entre no Onvio, abra o Messenger até aparecer a aba **Pendentes** e **feche o Chrome**.

Pronto: em até 30 segundos o card fica **AO VIVO**. O instalador:

- instala o Python (se faltar) e o Playwright, num ambiente só do leitor;
- confere o Google Chrome (e instala pelo `winget` se faltar);
- testa o token no painel e grava no `config.ini` (se o token não vier no zip, ele pergunta numa janela);
- instala tudo em `C:\Users\SEU_USUARIO\LeitorMessenger`;
- faz o leitor ligar junto com o Windows e cria dois atalhos na Área de Trabalho: **Leitor do Messenger - Ligar** e **Leitor do Messenger - Fazer login** (para quando a TV mostrar "Login necessário").

Para trocar o token, ou atualizar o leitor, é só rodar o `INSTALAR.bat` de novo. Se você rodar o instalador de dentro da pasta antiga (com a pasta `perfil_messenger`), ele reaproveita o login.

> O download do instalador precisa da pasta `leitor_local` no servidor, ao lado do `app.py`.

### Instalar à mão

1. Copie a pasta `leitor_local` para o PC do escritório. Pode reaproveitar a pasta `perfil_messenger` antiga para não precisar fazer login de novo.
2. Rode `instalar.bat` (uma vez).
3. No admin, abra **Atendimento** e copie o **endereço** e o **token** para a seção `[servidor]` do `config.ini`.
4. Rode `login_messenger.bat` (uma vez ou quando a sessão expirar) e depois `iniciar_leitor.bat`.

### Alerta de novo atendimento

Quando um cliente novo entra na fila, a TV:

- toca um sinal curto (dois toques suaves, cerca de 1 segundo);
- mostra um card no meio da tela com o nome, o departamento e o tempo de espera;
- se a opção estiver ligada, fala o nome em voz alta, por exemplo: *"Atenção. Cliente Maraca Tintas aguardando atendimento, departamento Fiscal."*

Cada parte liga e desliga em **Admin → Atendimento → Alerta de novo atendimento**. Ali também ficam o volume, o tempo do card na tela, o lembrete se o cliente continuar esperando e os botões **Ouvir aqui** e **Testar nas TVs**. Quem já estava na fila quando a TV ligou não dispara alerta.

**Som na TV:** os navegadores só liberam áudio depois de um toque na tela ou de um OK no controle. Enquanto o som não é liberado, aparece um aviso discreto no canto da TV. Se a TV for um PC com Chrome em tela cheia, dá para liberar o som de vez abrindo o Chrome assim:
`chrome.exe --kiosk --autoplay-policy=no-user-gesture-required https://SEU-DOMINIO/`
A voz depende do navegador ter voz em português. O Chrome e o Edge no Windows têm. Algumas Smart TVs não têm, e nesse caso toca só o sinal.

Se a internet cair, o leitor continua lendo e volta a enviar sozinho. A TV mostra "OFFLINE" depois de 90 segundos sem notícias.

> A pasta `perfil_messenger` dá acesso ao Messenger. Não envie essa pasta para ninguém e não coloque ela no servidor.

## Hospedar (servidor Linux com Docker)

Qualquer VPS serve: Hostinger, Locaweb, DigitalOcean, AWS Lightsail etc. Uma máquina com **2 vCPU, 2 GB de RAM e 40 GB de disco** dá conta. Os vídeos ficam no disco do servidor.

```bash
# 1. instale o Docker no servidor
curl -fsSL https://get.docker.com | sh

# 2. envie esta pasta para o servidor e entre nela
cd painel-web
cp .env.exemplo .env
nano .env            # preencha DOMINIO e ADMIN_SENHA

# 3. no seu provedor de DNS, crie um registro A: painel.seudominio -> IP do servidor

# 4. suba
docker compose up -d --build
```

O Caddy emite o certificado HTTPS sozinho. Libere as portas **80** e **443** no firewall do provedor.

- **Atualizar o código:** substitua os arquivos e rode `docker compose up -d --build`.
- **Backup:** guarde a pasta `dados/` (banco, vídeos, imagens e planilhas).
- **Logs:** `docker compose logs -f painel`

### Trazer os vídeos e a planilha da versão antiga

Com a pasta antiga `Avisos` copiada para o servidor:

```bash
docker compose run --rm -v "/caminho/Avisos:/antigo" painel python app.py importar /antigo
```

Também dá para fazer na mão: envie os vídeos e a planilha pelo painel.

### Testar no próprio PC (Windows)

Instale o Python e o FFmpeg (`winget install Gyan.FFmpeg`) e rode `rodar_no_windows.bat`. Abra `http://localhost:5000/admin`. A senha inicial aparece na janela e no arquivo `dados\SENHA_INICIAL_ADMIN.txt`.

## Segurança

- Senhas guardadas com hash, sessão de 12 h, bloqueio de 5 min depois de 5 senhas erradas e proteção CSRF.
- Só são aceitos arquivos de imagem e vídeo, e o conteúdo é validado (um arquivo renomeado para `.jpg` é recusado).
- **Chave da TV** (Configurações): quando está ligada, a tela só abre pelo endereço com `?chave=...`. Cada TV guarda a chave depois do primeiro acesso. **Recomendado**, porque o card mostra nomes de clientes.
- O token do leitor pode ser trocado a qualquer momento no admin.

## Estrutura

```
app.py                 servidor (Flask)
templates/tv.html      tela da TV
templates/admin/       login e painel do administrador
static/                logo, ícones, CSS e JS do admin
leitor_local/          vai para o PC do escritório (Messenger)
dados/                 criado automaticamente: banco, mídias, agenda
```

## Hospedar no PythonAnywhere

O PythonAnywhere não mantém threads de fundo nem tem CPU para converter vídeos. Por isso o WSGI de lá usa `CONVERTER_VIDEOS=nao`: o vídeo é publicado **como foi enviado**, na qualidade original, e a TV toca direto no navegador. Envie em **MP4 (H.264)** ou WEBM. Para o vídeo começar a tocar mais rápido, exporte com a opção "fast start" / "otimizado para web".

Para atualizar: `cd ~/painel-avisos-web && git pull` num console Bash e depois **Reload** na aba Web.
