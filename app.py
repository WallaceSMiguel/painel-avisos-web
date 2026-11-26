# -*- coding: utf-8 -*-
"""
PAINEL DE AVISOS - VALORIZAÇÃO (versão web)
===========================================

  /                 tela da TV (avisos + agenda das salas + atendimento)
  /admin            painel do administrador (login)
  /api/painel       dados da TV (avisos + salas + configurações)
  /api/atendimento  card do Messenger (alimentado pelo leitor local)

Tudo o que muda (avisos, vídeos, imagens, agenda, usuários) fica na
pasta DATA_DIR (padrão: ./dados), que é o único lugar a ser guardado
em backup ou montado como volume no Docker.
"""

import json
import mimetypes
import os
import queue
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
import unicodedata
import uuid
from datetime import date, datetime, timedelta
from datetime import time as dtime
from functools import wraps
from io import BytesIO
from pathlib import Path

from flask import (Flask, abort, g, jsonify, redirect, render_template,
                   request, send_file, send_from_directory, session, url_for)
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    Image = None

# ------------------------------------------------------------
# MIME correto para vídeos (navegadores de TV recusam tipo errado)
# ------------------------------------------------------------
mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/mp4", ".m4v")
mimetypes.add_type("video/webm", ".webm")
mimetypes.add_type("image/webp", ".webp")

# ============================================================
# CONFIGURAÇÃO (variáveis de ambiente / arquivo .env)
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "dados")).resolve()
MIDIA_DIR = DATA_DIR / "midia"
THUMB_DIR = MIDIA_DIR / "miniaturas"
AGENDA_DIR = DATA_DIR / "agenda"
TMP_DIR = DATA_DIR / "tmp"
DB_FILE = DATA_DIR / "painel.db"
ATEND_FILE = DATA_DIR / "atendimento.json"
AGENDA_JSON = AGENDA_DIR / "agenda.json"
AGENDA_XLSX = AGENDA_DIR / "agenda_atual.xlsx"

for pasta in (DATA_DIR, MIDIA_DIR, THUMB_DIR, AGENDA_DIR, TMP_DIR):
    pasta.mkdir(parents=True, exist_ok=True)

FUSO = os.environ.get("FUSO_HORARIO", "America/Sao_Paulo")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "2048"))
ATENDIMENTO_VALIDADE = 90          # s sem notícia do leitor = leitor parado
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
# CONVERTER_VIDEOS=nao: publica o vídeo como foi enviado, sem fila nem FFmpeg
# (para hospedagens sem threads de fundo / com pouca CPU, ex.: PythonAnywhere).
CONVERTER_VIDEOS = os.environ.get("CONVERTER_VIDEOS", "sim").lower() in {"sim", "1", "true"}
EXT_VIDEO_DIRETO = {".mp4", ".m4v", ".webm", ".mov"}

EXT_IMAGEM = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
EXT_VIDEO = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".wmv", ".mpg", ".mpeg", ".3gp"}
EXT_PLANILHA = {".xlsx", ".xlsm"}


def agora():
    if ZoneInfo:
        try:
            return datetime.now(ZoneInfo(FUSO)).replace(tzinfo=None)
        except Exception:
            pass
    return datetime.now()


def _segredo_persistente(nome_arquivo, gerar):
    """Lê um segredo de DATA_DIR ou cria um novo (sobrevive a reinícios)."""
    arq = DATA_DIR / nome_arquivo
    if arq.exists():
        valor = arq.read_text(encoding="utf-8").strip()
        if valor:
            return valor
    valor = gerar()
    arq.write_text(valor, encoding="utf-8")
    try:
        os.chmod(arq, 0o600)
    except Exception:
        pass
    return valor


app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or _segredo_persistente(".secret_key", lambda: secrets.token_hex(32)),
    MAX_CONTENT_LENGTH=MAX_UPLOAD_MB * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SEGURO", "nao").lower() in {"sim", "1", "true"},
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    JSON_AS_ASCII=False,
)
app.json.ensure_ascii = False

# atrás de proxy (Caddy / Nginx): respeita X-Forwarded-*
if os.environ.get("ATRAS_DE_PROXY", "nao").lower() in {"sim", "1", "true"}:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


# ============================================================
# BANCO DE DADOS (SQLite)
# ============================================================

ESQUEMA = """
CREATE TABLE IF NOT EXISTS avisos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo        TEXT DEFAULT '',
    descricao     TEXT DEFAULT '',
    arquivo       TEXT DEFAULT '',
    tipo          TEXT DEFAULT 'imagem',
    posicao       TEXT DEFAULT 'carrossel',
    ativo         INTEGER DEFAULT 1,
    ordem         INTEGER DEFAULT 9999,
    duracao       INTEGER,
    inicio        TEXT DEFAULT '',
    fim           TEXT DEFAULT '',
    status        TEXT DEFAULT 'pronto',
    progresso     INTEGER DEFAULT 100,
    erro          TEXT DEFAULT '',
    nome_original TEXT DEFAULT '',
    tamanho       INTEGER DEFAULT 0,
    largura       INTEGER,
    altura        INTEGER,
    duracao_video REAL,
    criado_por    TEXT DEFAULT '',
    criado_em     TEXT,
    atualizado_em TEXT
);
CREATE TABLE IF NOT EXISTS config (
    chave TEXT PRIMARY KEY,
    valor TEXT
);
CREATE TABLE IF NOT EXISTS usuarios (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    login      TEXT UNIQUE NOT NULL,
    nome       TEXT DEFAULT '',
    senha_hash TEXT NOT NULL,
    criado_em  TEXT
);
CREATE TABLE IF NOT EXISTS historico (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    quando  TEXT,
    usuario TEXT,
    acao    TEXT
);
"""

CONFIG_PADRAO = {
    "empresa_titulo": "Valorização",
    "empresa_subtitulo": "Assessoria Contábil",
    "rodape": "Valorização Assessoria Contábil  •  Departamento de TI",
    "tempo_imagem": "8",
    "mostrar_atendimento": "sim",
    "max_clientes_card": "3",
    "ocultar_reunioes_passadas": "nao",
    # alerta de novo atendimento na TV
    "alerta_ativo": "sim",          # liga/desliga a função inteira
    "alerta_card": "sim",           # card no meio da tela
    "alerta_som": "sim",            # sinal sonoro curto
    "alerta_voz": "sim",            # falar o nome do cliente
    "alerta_volume": "60",          # 0 a 100
    "alerta_duracao": "12",         # segundos do card na tela
    "alerta_repetir_min": "0",      # lembrar de novo a cada N min (0 = não)
    "alerta_teste": "0",            # carimbo do botão "Testar nas TVs"
    "tv_chave": os.environ.get("TV_CHAVE", ""),
    "leitor_token": os.environ.get("LEITOR_TOKEN", ""),
}


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_FILE, timeout=30)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db


def db_avulso():
    """Conexão para threads de fundo (fora do contexto de request)."""
    con = sqlite3.connect(DB_FILE, timeout=30)
    con.row_factory = sqlite3.Row
    return con


@app.teardown_appcontext
def fechar_db(_erro):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def iniciar_banco():
    con = db_avulso()
    con.executescript(ESQUEMA)
    for chave, valor in CONFIG_PADRAO.items():
        con.execute("INSERT OR IGNORE INTO config (chave, valor) VALUES (?, ?)", (chave, valor))
    # token do leitor do Messenger: gera um se não houver
    tok = con.execute("SELECT valor FROM config WHERE chave='leitor_token'").fetchone()
    if not tok or not tok["valor"]:
        con.execute("UPDATE config SET valor=? WHERE chave='leitor_token'", (secrets.token_urlsafe(32),))
    # primeiro administrador
    if not con.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone():
        login = os.environ.get("ADMIN_USUARIO", "admin").strip() or "admin"
        senha = os.environ.get("ADMIN_SENHA", "").strip()
        if not senha:
            senha = secrets.token_urlsafe(9)
            (DATA_DIR / "SENHA_INICIAL_ADMIN.txt").write_text(
                f"Usuário: {login}\nSenha:   {senha}\n\nTroque a senha em Configurações e apague este arquivo.\n",
                encoding="utf-8")
            print("=" * 60)
            print(f" Administrador criado -> usuário: {login}   senha: {senha}")
            print(f" (também gravado em {DATA_DIR / 'SENHA_INICIAL_ADMIN.txt'})")
            print("=" * 60)
        con.execute("INSERT INTO usuarios (login, nome, senha_hash, criado_em) VALUES (?,?,?,?)",
                    (login, "Administrador", generate_password_hash(senha), agora().isoformat(timespec="seconds")))
    con.commit()
    con.close()


def cfg_todas(con=None):
    con = con or db()
    return {r["chave"]: r["valor"] for r in con.execute("SELECT chave, valor FROM config")}


def cfg(chave, padrao=""):
    r = db().execute("SELECT valor FROM config WHERE chave=?", (chave,)).fetchone()
    return r["valor"] if r and r["valor"] is not None else padrao


def cfg_salvar(chave, valor, con=None):
    c = con or db()
    c.execute("INSERT INTO config (chave, valor) VALUES (?, ?) "
              "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor", (chave, str(valor)))
    if con is None:
        c.commit()


def registrar(acao, usuario=None, con=None):
    c = con or db()
    usuario = usuario or session.get("nome") or session.get("login") or "sistema"
    c.execute("INSERT INTO historico (quando, usuario, acao) VALUES (?,?,?)",
              (agora().isoformat(timespec="seconds"), usuario, acao))
    c.execute("DELETE FROM historico WHERE id NOT IN (SELECT id FROM historico ORDER BY id DESC LIMIT 300)")
    if con is None:
        c.commit()


def sim(valor):
    return str(valor or "").strip().lower() in {"sim", "s", "1", "true", "on", "yes"}


# ============================================================
# AUTENTICAÇÃO
# ============================================================

TENTATIVAS = {}          # ip -> [falhas, bloqueado_ate]
TRAVA_TENTATIVAS = threading.Lock()


def ip_cliente():
    return request.remote_addr or "?"


def login_obrigatorio(f):
    @wraps(f)
    def interno(*a, **kw):
        if not session.get("uid"):
            if request.path.startswith("/admin/api/"):
                return jsonify({"erro": "Sessão expirada. Entre novamente."}), 401
            return redirect(url_for("admin_login", proximo=request.path))
        # proteção CSRF para tudo que altera dados
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            enviado = request.headers.get("X-CSRF-Token") or request.form.get("csrf")
            if not enviado or not secrets.compare_digest(enviado, session.get("csrf", "")):
                return jsonify({"erro": "Token de segurança inválido. Recarregue a página."}), 400
        return f(*a, **kw)
    return interno


def tv_liberada():
    """A tela da TV pode exigir uma chave (configurável no admin)."""
    chave = cfg("tv_chave")
    if not chave:
        return True
    if session.get("uid"):
        return True
    enviada = request.args.get("chave") or request.cookies.get("tv_chave") or ""
    return bool(enviada) and secrets.compare_digest(enviada, chave)


def tv_obrigatoria(f):
    @wraps(f)
    def interno(*a, **kw):
        if not tv_liberada():
            if request.path.startswith("/api/") or request.path.startswith("/midia/"):
                return jsonify({"erro": "acesso restrito"}), 403
            return render_template("tv_bloqueada.html"), 403
        return f(*a, **kw)
    return interno


@app.after_request
def cabecalhos_seguranca(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if request.path.startswith("/admin"):
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


# ============================================================
# UTILITÁRIOS
# ============================================================

def texto(v):
    return "" if v is None else str(v).strip()


def normalizar(v):
    v = unicodedata.normalize("NFD", texto(v))
    v = "".join(c for c in v if unicodedata.category(c) != "Mn")
    return "".join(c.lower() for c in v if c.isalnum())


def tamanho_legivel(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u in ("B", "KB") else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} GB"


def aviso_dict(r):
    d = dict(r)
    d["ativo"] = bool(d["ativo"])
    d["media_url"] = f"/midia/{d['arquivo']}" if d.get("arquivo") else ""
    d["miniatura"] = f"/midia/miniaturas/{d['id']}.jpg" if (THUMB_DIR / f"{d['id']}.jpg").exists() else ""
    d["tamanho_fmt"] = tamanho_legivel(d.get("tamanho"))
    return d


def ler_data_hora(valor):
    valor = texto(valor)
    if not valor:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(valor, fmt)
        except ValueError:
            continue
    return None


def no_periodo(aviso, momento):
    ini = ler_data_hora(aviso["inicio"])
    fim = ler_data_hora(aviso["fim"])
    if ini and momento < ini:
        return False
    if fim:
        if len(texto(aviso["fim"])) == 10:      # só a data: vale o dia todo
            fim = fim.replace(hour=23, minute=59, second=59)
        if momento > fim:
            return False
    return True


# ============================================================
# MÍDIA: imagens
# ============================================================

def processar_imagem(origem: Path, ext: str):
    """
    Valida e prepara a imagem para a TV:
    - gira conforme o EXIF (foto de celular)
    - reduz para no máximo 1920x1080 (TVs sofrem com imagens enormes)
    - BMP/WEBP viram JPG/PNG (formatos que qualquer TV abre)
    GIF animado é mantido como está.
    """
    nome = uuid.uuid4().hex
    if Image is None:
        destino = MIDIA_DIR / f"{nome}{ext}"
        shutil.move(str(origem), destino)
        return destino.name, None, None

    with Image.open(origem) as im:
        im.verify()
    with Image.open(origem) as im:
        if ext == ".gif" and getattr(im, "is_animated", False):
            destino = MIDIA_DIR / f"{nome}.gif"
            shutil.move(str(origem), destino)
            return destino.name, im.width, im.height
        im = ImageOps.exif_transpose(im)
        im.thumbnail((1920, 1080), Image.LANCZOS)
        tem_alfa = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
        if tem_alfa:
            destino = MIDIA_DIR / f"{nome}.png"
            im.convert("RGBA").save(destino, "PNG", optimize=True)
        else:
            destino = MIDIA_DIR / f"{nome}.jpg"
            im.convert("RGB").save(destino, "JPEG", quality=90, optimize=True, progressive=False)
        largura, altura = im.size
    try:
        origem.unlink()
    except Exception:
        pass
    return destino.name, largura, altura


def gerar_miniatura(aviso_id, arquivo: Path, tipo):
    destino = THUMB_DIR / f"{aviso_id}.jpg"
    try:
        if tipo == "video" and FFMPEG:
            subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", "1", "-i", str(arquivo),
                            "-frames:v", "1", "-vf", "scale=480:-2", str(destino)],
                           timeout=60, capture_output=True)
            if not destino.exists():
                subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(arquivo),
                                "-frames:v", "1", "-vf", "scale=480:-2", str(destino)],
                               timeout=60, capture_output=True)
        elif tipo == "imagem" and Image is not None:
            with Image.open(arquivo) as im:
                im = ImageOps.exif_transpose(im)
                im.thumbnail((480, 300))
                fundo = Image.new("RGB", im.size, (0, 0, 0))
                im = im.convert("RGBA")
                fundo.paste(im, mask=im.split()[3])
                fundo.save(destino, "JPEG", quality=82)
    except Exception as erro:
        print("⚠ miniatura:", erro)


# ============================================================
# MÍDIA: vídeos (fila de conversão para o formato das TVs)
# ============================================================

FILA_VIDEOS = queue.Queue()
_trabalhador_iniciado = False
_trava_trabalhador = threading.Lock()


def ffprobe(caminho: Path):
    if not FFPROBE:
        return {}
    try:
        r = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_streams",
                            "-show_format", str(caminho)], capture_output=True, timeout=60)
        return json.loads(r.stdout or b"{}")
    except Exception:
        return {}


def moov_no_inicio(caminho: Path):
    """True se o índice do MP4 (moov) vem antes dos dados (faststart)."""
    try:
        total = caminho.stat().st_size
        with open(caminho, "rb") as f:
            pos = 0
            while pos < total:
                f.seek(pos)
                cab = f.read(16)
                if len(cab) < 8:
                    break
                tam = int.from_bytes(cab[0:4], "big")
                tipo = cab[4:8]
                if tam == 1 and len(cab) >= 16:
                    tam = int.from_bytes(cab[8:16], "big")
                elif tam == 0:
                    tam = total - pos
                if tipo == b"moov":
                    return True
                if tipo == b"mdat":
                    return False
                if tam < 8:
                    break
                pos += tam
    except Exception:
        pass
    return False


def video_ja_compativel(info):
    """H.264 até 1080p, yuv420p, áudio AAC (ou sem áudio) = basta reorganizar."""
    streams = info.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = [s for s in streams if s.get("codec_type") == "audio"]
    if not v or v.get("codec_name") != "h264":
        return False
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    if max(w, h) > 1920 or min(w, h) > 1080:
        return False
    if v.get("pix_fmt") not in ("yuv420p", "yuvj420p"):
        return False
    if (v.get("profile") or "").lower() not in {"baseline", "constrained baseline", "main", "high"}:
        return False
    try:
        if int(v.get("level") or 0) > 42:
            return False
    except ValueError:
        pass
    if any(s.get("codec_name") != "aac" for s in a):
        return False
    fps = v.get("avg_frame_rate") or "0/1"
    try:
        n, d = fps.split("/")
        if float(d) and float(n) / float(d) > 31:
            return False
    except Exception:
        pass
    return True


def _atualizar_aviso(con, aviso_id, **campos):
    campos["atualizado_em"] = agora().isoformat(timespec="seconds")
    sets = ", ".join(f"{k}=?" for k in campos)
    con.execute(f"UPDATE avisos SET {sets} WHERE id=?", (*campos.values(), aviso_id))
    con.commit()


def converter_video(aviso_id, origem: Path):
    con = db_avulso()
    try:
        if not con.execute("SELECT 1 FROM avisos WHERE id=?", (aviso_id,)).fetchone():
            origem.unlink(missing_ok=True)
            return   # aviso apagado enquanto esperava na fila

        nome = uuid.uuid4().hex + ".mp4"
        saida_tmp = TMP_DIR / (nome + ".parcial.mp4")
        destino = MIDIA_DIR / nome

        if not FFMPEG or not CONVERTER_VIDEOS:
            # sem conversão: usa o arquivo como veio (a TV toca direto)
            ext = origem.suffix.lower()
            if ext not in EXT_VIDEO_DIRETO:
                raise RuntimeError("Envie o vídeo em MP4 (H.264) ou WEBM: este servidor não converte vídeos")
            nome = uuid.uuid4().hex + (".mp4" if ext == ".m4v" else ext)
            destino = MIDIA_DIR / nome
            shutil.move(str(origem), destino)
            alerta = "" if destino.suffix != ".mp4" or moov_no_inicio(destino) else \
                "Vídeo sem 'faststart': pode demorar um pouco para começar a tocar na TV."
            _atualizar_aviso(con, aviso_id, arquivo=nome, status="pronto", progresso=100,
                             erro=alerta, tamanho=destino.stat().st_size)
            gerar_miniatura(aviso_id, destino, "video")
            return

        info = ffprobe(origem)
        try:
            duracao = float((info.get("format") or {}).get("duration") or 0)
        except ValueError:
            duracao = 0
        if not any(s.get("codec_type") == "video" for s in info.get("streams") or []):
            raise RuntimeError("O arquivo enviado não contém vídeo (ou está corrompido)")

        _atualizar_aviso(con, aviso_id, status="processando", progresso=1, duracao_video=duracao or None)

        if video_ja_compativel(info):
            # já está no formato certo: só coloca o índice no início (segundos)
            cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(origem),
                   "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-movflags", "+faststart",
                   "-progress", "pipe:1", "-nostats", str(saida_tmp)]
        else:
            # mesmos parâmetros do antigo converter_videos.bat
            cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(origem),
                   "-map", "0:v:0", "-map", "0:a:0?",
                   "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
                          "pad=ceil(iw/2)*2:ceil(ih/2)*2,fps=30",
                   "-c:v", "libx264", "-preset", os.environ.get("FFMPEG_PRESET", "veryfast"),
                   "-profile:v", "main", "-level", "4.0", "-pix_fmt", "yuv420p",
                   "-crf", "23", "-maxrate", "5M", "-bufsize", "10M",
                   "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "44100",
                   "-movflags", "+faststart", "-f", "mp4",
                   "-progress", "pipe:1", "-nostats", str(saida_tmp)]

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        ultimo = 0
        for linha in proc.stdout:
            if linha.startswith("out_time_us=") or linha.startswith("out_time_ms="):
                try:
                    us = int(linha.split("=", 1)[1])
                except ValueError:
                    continue
                if duracao > 0:
                    pct = max(1, min(99, int(us / 1_000_000 / duracao * 100)))
                    if pct >= ultimo + 2:
                        ultimo = pct
                        _atualizar_aviso(con, aviso_id, progresso=pct)
        proc.wait()
        if proc.returncode != 0 or not saida_tmp.exists():
            erro = (proc.stderr.read() if proc.stderr else "")[-400:]
            raise RuntimeError("Falha ao converter o vídeo. " + erro.strip())

        if not con.execute("SELECT 1 FROM avisos WHERE id=?", (aviso_id,)).fetchone():
            saida_tmp.unlink(missing_ok=True)
            return

        shutil.move(str(saida_tmp), destino)
        info2 = ffprobe(destino)
        v = next((s for s in info2.get("streams") or [] if s.get("codec_type") == "video"), {})
        _atualizar_aviso(con, aviso_id, arquivo=nome, status="pronto", progresso=100, erro="",
                         tamanho=destino.stat().st_size, largura=v.get("width"), altura=v.get("height"))
        gerar_miniatura(aviso_id, destino, "video")
        registrar(f"Vídeo pronto e publicado (aviso #{aviso_id})", "sistema", con)
        con.commit()
        print(f"✔ vídeo do aviso #{aviso_id} pronto: {nome}")
    except Exception as erro:
        print(f"⚠ vídeo do aviso #{aviso_id}: {erro}")
        try:
            _atualizar_aviso(con, aviso_id, status="erro", erro=str(erro)[:500])
        except Exception:
            pass
    finally:
        try:
            origem.unlink(missing_ok=True)
        except Exception:
            pass
        con.close()


def trabalhador_videos():
    while True:
        aviso_id, origem = FILA_VIDEOS.get()
        try:
            converter_video(aviso_id, Path(origem))
        finally:
            FILA_VIDEOS.task_done()


def garantir_trabalhador():
    global _trabalhador_iniciado
    with _trava_trabalhador:
        if _trabalhador_iniciado:
            return
        if not CONVERTER_VIDEOS:
            _trabalhador_iniciado = True
            con = db_avulso()
            pendentes = [r["id"] for r in con.execute(
                "SELECT id FROM avisos WHERE status IN ('fila','processando') AND tipo='video' ORDER BY id")]
            con.close()
            for aviso_id in pendentes:
                pendente = next(TMP_DIR.glob(f"envio_{aviso_id}_*"), None)
                if pendente:
                    converter_video(aviso_id, pendente)
            return
        threading.Thread(target=trabalhador_videos, daemon=True, name="videos").start()
        _trabalhador_iniciado = True
        # retoma conversões interrompidas (servidor reiniciado no meio)
        con = db_avulso()
        for r in con.execute("SELECT id FROM avisos WHERE status IN ('fila','processando') ORDER BY id"):
            pendente = next(TMP_DIR.glob(f"envio_{r['id']}_*"), None)
            if pendente:
                FILA_VIDEOS.put((r["id"], str(pendente)))
            else:
                con.execute("UPDATE avisos SET status='erro', erro='Envio interrompido: mande o vídeo de novo' "
                            "WHERE id=?", (r["id"],))
        con.commit()
        con.close()
        # limpa sobras de conversões
        for sobra in TMP_DIR.glob("*.parcial.mp4"):
            sobra.unlink(missing_ok=True)


# ============================================================
# AGENDA DAS SALAS (planilha)
# ============================================================

def _data(valor):
    if valor is None or texto(valor) == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, (int, float)) and 20000 < valor < 80000:      # nº de série do Excel
        return (datetime(1899, 12, 30) + timedelta(days=float(valor))).date()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(texto(valor), fmt).date()
        except ValueError:
            continue
    return None


def _hora(valor):
    if valor is None or texto(valor) == "":
        return ""
    if isinstance(valor, (dtime, datetime)):
        return valor.strftime("%H:%M")
    if isinstance(valor, timedelta):
        m = int(valor.total_seconds() // 60)
        return f"{m // 60:02d}:{m % 60:02d}"
    if isinstance(valor, float) and 0 <= valor < 1:                      # fração do dia
        m = round(valor * 24 * 60)
        return f"{m // 60:02d}:{m % 60:02d}"
    t = texto(valor).lower().replace("h", ":").rstrip(":")
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?(?::\d{2})?$", t)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}"
    return texto(valor)


def _status_sala(valor):
    s = texto(valor).upper()
    if any(p in s for p in ("OCUP", "EM USO", "USANDO")):
        return "OCUPADA"
    if any(p in s for p in ("RESERV", "AGENDAD", "CONFIRM")):
        return "RESERVADA"
    if not s or any(p in s for p in ("LIVRE", "DISPON", "LIBERAD", "VAZIA")):
        return "DISPONIVEL"
    return s


COLUNAS_AGENDA = {
    "sala": ["sala", "nome", "reuniao", "reunião", "assunto", "evento", "titulo", "título", "local"],
    "status": ["status", "situacao", "situação", "estado"],
    "responsavel": ["responsavel", "responsável", "organizador", "solicitante", "quem"],
    "data": ["data", "dia", "datareuniao", "data da reuniao"],
    "hora_inicial": ["horainicial", "hora inicial", "inicio", "início", "horainicio", "hora", "de"],
    "hora_final": ["horafinal", "hora final", "fim", "termino", "término", "horafim", "ate", "até"],
}


def ler_planilha_agenda(caminho: Path):
    """
    Lê a aba "Salas" (ou a primeira aba) e devolve (reunioes, avisos_de_leitura).
    Aceita a mesma planilha usada antes na pasta da rede.
    """
    wb = load_workbook(caminho, data_only=True, read_only=True)
    alertas = []
    try:
        aba = None
        for nome in wb.sheetnames:
            if normalizar(nome) in {"salas", "agenda", "agendadassalas", "reunioes"}:
                aba = wb[nome]
                break
        if aba is None:
            aba = wb[wb.sheetnames[0]]
            alertas.append(f"Aba 'Salas' não encontrada: usei a aba '{aba.title}'.")

        linhas = list(aba.iter_rows(values_only=True))
    finally:
        wb.close()

    # cabeçalho = primeira linha que tenha uma coluna "Sala" (ou equivalente)
    idx_cab, mapa = None, {}
    for i, linha in enumerate(linhas[:15]):
        normal = [normalizar(c) for c in linha]
        achou = {}
        for campo, nomes in COLUNAS_AGENDA.items():
            alvos = {normalizar(n) for n in nomes}
            for j, c in enumerate(normal):
                if c and c in alvos and j not in achou.values():
                    achou[campo] = j
                    break
        if "sala" in achou:
            idx_cab, mapa = i, achou
            break
    if idx_cab is None:
        raise ValueError("Não encontrei a coluna 'Sala' na planilha. "
                         "Use o modelo: ID | Sala | Status | Responsável | Data | Hora Inicial | Hora Final")

    for campo in ("data", "hora_inicial", "responsavel"):
        if campo not in mapa:
            alertas.append(f"Coluna de {campo.replace('_', ' ')} não encontrada.")

    def pegar(linha, campo):
        j = mapa.get(campo)
        return linha[j] if j is not None and j < len(linha) else None

    reunioes = []
    for n, linha in enumerate(linhas[idx_cab + 1:], start=idx_cab + 2):
        nome = texto(pegar(linha, "sala"))
        if not nome or nome in {"0", "-", "—", "N/A"}:
            continue
        bruto_data = pegar(linha, "data")
        d = _data(bruto_data)
        if bruto_data not in (None, "") and not d:
            alertas.append(f"Linha {n}: data '{texto(bruto_data)}' não reconhecida.")
        reunioes.append({
            "sala": nome,
            "nome": nome,
            "status": _status_sala(pegar(linha, "status")),
            "responsavel": texto(pegar(linha, "responsavel")),
            "data": d.isoformat() if d else "",
            "data_formatada": d.strftime("%d/%m/%Y") if d else texto(bruto_data),
            "hora_inicial_fmt": _hora(pegar(linha, "hora_inicial")),
            "hora_final_fmt": _hora(pegar(linha, "hora_final")),
        })

    # ordena por data e hora (sem data vai para o fim)
    reunioes.sort(key=lambda r: (r["data"] or "9999-12-31", r["hora_inicial_fmt"] or "99:99"))
    return reunioes, alertas


def agenda_atual():
    try:
        return json.loads(AGENDA_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {"reunioes": [], "arquivo": "", "enviado_em": "", "enviado_por": "", "alertas": []}


# ============================================================
# ATENDIMENTO (Messenger)
# ============================================================

ATEND_MEMORIA = {"dados": None}
TRAVA_ATEND = threading.Lock()


def atendimento_ler():
    with TRAVA_ATEND:
        if ATEND_MEMORIA["dados"] is None and ATEND_FILE.exists():
            try:
                ATEND_MEMORIA["dados"] = json.loads(ATEND_FILE.read_text(encoding="utf-8"))
            except Exception:
                ATEND_MEMORIA["dados"] = None
        return dict(ATEND_MEMORIA["dados"] or {})


def atendimento_gravar(dados):
    dados["recebido_ts"] = time.time()
    with TRAVA_ATEND:
        ATEND_MEMORIA["dados"] = dados
        tmp = ATEND_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, ATEND_FILE)


def alerta_config(c=None):
    c = c or cfg_todas()

    def inteiro(chave, padrao, minimo, maximo):
        try:
            return max(minimo, min(maximo, int(c.get(chave) or padrao)))
        except ValueError:
            return padrao
    return {
        "ativo": sim(c.get("alerta_ativo", "sim")),
        "card": sim(c.get("alerta_card", "sim")),
        "som": sim(c.get("alerta_som", "sim")),
        "voz": sim(c.get("alerta_voz", "sim")),
        "volume": inteiro("alerta_volume", 60, 0, 100),
        "duracao": inteiro("alerta_duracao", 12, 4, 120),
        "repetir_min": inteiro("alerta_repetir_min", 0, 0, 240),
        "teste": c.get("alerta_teste", "0"),
    }


def atendimento_para_tv():
    d = _atendimento_para_tv()
    d["alerta"] = alerta_config()
    return d


def _atendimento_para_tv():
    if not sim(cfg("mostrar_atendimento", "sim")):
        return {"status": "desativado"}
    d = atendimento_ler()
    if not d:
        return {"status": "sem_leitor",
                "mensagem": "Aguardando o leitor do Messenger (PC do escritório)"}
    if d.get("status") == "desativado":
        return d
    idade = time.time() - float(d.get("recebido_ts") or d.get("atualizado_ts") or 0)
    if idade > ATENDIMENTO_VALIDADE:
        d["status"] = "sem_leitor"
        d["mensagem"] = "O leitor do Messenger parou (PC do escritório desligado ou sem internet)"
    d.pop("textos_lidos", None)
    d["max_clientes"] = int(cfg("max_clientes_card", "3") or 3)
    return d


# ============================================================
# ROTAS PÚBLICAS (TV)
# ============================================================

@app.route("/")
def tv():
    chave = cfg("tv_chave")
    enviada = request.args.get("chave")
    if chave and enviada and secrets.compare_digest(enviada, chave):
        # grava a chave num cookie e limpa o endereço
        resp = redirect(url_for("tv", **{k: v for k, v in request.args.items() if k != "chave"}))
        resp.set_cookie("tv_chave", chave, max_age=60 * 60 * 24 * 400, httponly=True, samesite="Lax",
                        secure=app.config["SESSION_COOKIE_SECURE"])
        return resp
    if not tv_liberada():
        return render_template("tv_bloqueada.html"), 403
    return render_template("tv.html")


@app.route("/api/painel")
@tv_obrigatoria
def api_painel():
    momento = agora()
    c = cfg_todas()
    linhas = db().execute(
        "SELECT * FROM avisos WHERE ativo=1 AND status='pronto' AND arquivo<>'' ORDER BY ordem, id").fetchall()
    avisos = []
    padrao = int(c.get("tempo_imagem") or 8)
    for r in linhas:
        if not no_periodo(r, momento):
            continue
        if not (MIDIA_DIR / r["arquivo"]).exists():
            continue
        avisos.append({
            "id": r["id"],
            "titulo": r["titulo"] or "",
            "descricao": r["descricao"] or "",
            "arquivo": r["arquivo"],
            "imagem": r["arquivo"],
            "tipo": r["tipo"],
            "media_url": f"/midia/{r['arquivo']}",
            "posicao": "card1" if r["posicao"] == "destaque" else "carrossel",
            "duracao": int(r["duracao"] or padrao),
        })

    agenda = agenda_atual()
    salas = agenda.get("reunioes") or []
    if sim(c.get("ocultar_reunioes_passadas")):
        hoje = momento.date().isoformat()
        salas = [s for s in salas if not s.get("data") or s["data"] >= hoje]

    resp = jsonify({
        "avisos": avisos,
        "salas": salas,
        "configuracoes": {
            "empresa_titulo": c.get("empresa_titulo", ""),
            "empresa_subtitulo": c.get("empresa_subtitulo", ""),
            "rodape": c.get("rodape", ""),
            "tempo_imagem": padrao,
        },
    })
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/atendimento")
@tv_obrigatoria
def api_atendimento():
    resp = jsonify(atendimento_para_tv())
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _token_do_leitor_ok():
    token = (request.headers.get("Authorization") or "").replace("Bearer", "").strip()
    certo = cfg("leitor_token")
    return bool(token and certo and secrets.compare_digest(token, certo))


@app.route("/api/atendimento/verificar")
def api_atendimento_verificar():
    """Usado pelo instalador do leitor para testar o token (não altera nada)."""
    if not _token_do_leitor_ok():
        return jsonify({"erro": "token inválido"}), 401
    return jsonify({"ok": True})


@app.route("/api/atendimento/push", methods=["POST"])
def api_atendimento_push():
    """Recebe os dados do leitor_messenger.py que roda no PC do escritório."""
    if not _token_do_leitor_ok():
        return jsonify({"erro": "token inválido"}), 401
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({"erro": "JSON inválido"}), 400
    # só o que a TV usa (limita tamanho e evita lixo)
    limpo = {
        "status": texto(dados.get("status"))[:40] or "ok",
        "mensagem": texto(dados.get("mensagem"))[:300],
        "pendentes": int(dados.get("pendentes") or 0),
        "em_atendimento": dados.get("em_atendimento") if isinstance(dados.get("em_atendimento"), int) else None,
        "clientes": [],
        "atualizado_em": texto(dados.get("atualizado_em"))[:40],
    }
    for c in (dados.get("clientes") or [])[:30]:
        if isinstance(c, dict):
            limpo["clientes"].append({
                "nome": texto(c.get("nome"))[:120],
                "departamento": texto(c.get("departamento"))[:80],
                "hora": texto(c.get("hora"))[:10],
                "espera_min": int(c.get("espera_min") or 0),
            })
    atendimento_gravar(limpo)
    return jsonify({"ok": True, "mostrar": sim(cfg("mostrar_atendimento", "sim"))})


@app.route("/midia/<path:nome>")
@tv_obrigatoria
def midia(nome):
    # arquivos têm nome único -> cache longo na TV (não baixa de novo a cada volta)
    resp = send_from_directory(MIDIA_DIR, nome, conditional=True, max_age=60 * 60 * 24 * 7)
    resp.headers["Accept-Ranges"] = "bytes"
    return resp


@app.route("/saude")
def saude():
    return jsonify({"ok": True, "ffmpeg": bool(FFMPEG), "hora": agora().isoformat(timespec="seconds")})


# ============================================================
# ADMIN: login
# ============================================================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    erro = ""
    if request.method == "POST":
        ip = ip_cliente()
        with TRAVA_TENTATIVAS:
            falhas, ate = TENTATIVAS.get(ip, [0, 0])
        if ate > time.time():
            erro = f"Muitas tentativas. Aguarde {int((ate - time.time()) // 60) + 1} min."
        else:
            login = texto(request.form.get("login")).lower()
            senha = request.form.get("senha") or ""
            u = db().execute("SELECT * FROM usuarios WHERE lower(login)=?", (login,)).fetchone()
            if u and check_password_hash(u["senha_hash"], senha):
                with TRAVA_TENTATIVAS:
                    TENTATIVAS.pop(ip, None)
                session.clear()
                session.permanent = True
                session.update(uid=u["id"], login=u["login"], nome=u["nome"] or u["login"],
                               csrf=secrets.token_urlsafe(24))
                registrar("Entrou no painel")
                proximo = request.args.get("proximo") or ""
                if not proximo.startswith("/admin"):
                    proximo = url_for("admin")
                return redirect(proximo)
            with TRAVA_TENTATIVAS:
                falhas += 1
                TENTATIVAS[ip] = [falhas, time.time() + 300 if falhas >= 5 else 0]
                if falhas >= 5:
                    TENTATIVAS[ip][0] = 0
            erro = "Usuário ou senha incorretos."
            time.sleep(0.6)
    return render_template("admin/login.html", erro=erro)


@app.route("/admin/sair")
def admin_sair():
    session.clear()
    return redirect(url_for("admin_login"))


@app.route("/admin")
@app.route("/admin/")
@login_obrigatorio
def admin():
    return render_template("admin/painel.html", csrf=session["csrf"], usuario=session.get("nome"),
                           max_upload_mb=MAX_UPLOAD_MB, ffmpeg=bool(FFMPEG))


# ============================================================
# ADMIN: API - visão geral
# ============================================================

@app.route("/admin/api/resumo")
@login_obrigatorio
def api_resumo():
    con = db()
    momento = agora()
    todos = con.execute("SELECT * FROM avisos ORDER BY ordem, id").fetchall()
    no_ar = [r for r in todos if r["ativo"] and r["status"] == "pronto" and no_periodo(r, momento)]
    agenda = agenda_atual()
    hoje = momento.date().isoformat()
    reunioes_hoje = [r for r in agenda.get("reunioes", []) if r.get("data") == hoje]
    proximas = [r for r in agenda.get("reunioes", []) if r.get("data") and r["data"] >= hoje][:5]
    espaco = sum(f.stat().st_size for f in MIDIA_DIR.glob("*") if f.is_file())
    historico = [dict(r) for r in con.execute("SELECT * FROM historico ORDER BY id DESC LIMIT 12")]
    return jsonify({
        "avisos_total": len(todos),
        "avisos_no_ar": len(no_ar),
        "processando": sum(1 for r in todos if r["status"] in ("fila", "processando")),
        "reunioes_total": len(agenda.get("reunioes", [])),
        "reunioes_hoje": reunioes_hoje,
        "proximas": proximas,
        "agenda_enviada_em": agenda.get("enviado_em", ""),
        "agenda_enviada_por": agenda.get("enviado_por", ""),
        "atendimento": atendimento_para_tv(),
        "espaco_midia": tamanho_legivel(espaco),
        "historico": historico,
        "ffmpeg": bool(FFMPEG),
    })


# ============================================================
# ADMIN: API - avisos
# ============================================================

@app.route("/admin/api/avisos")
@login_obrigatorio
def api_avisos_lista():
    momento = agora()
    lista = []
    for r in db().execute("SELECT * FROM avisos ORDER BY ordem, id"):
        d = aviso_dict(r)
        d["no_periodo"] = no_periodo(r, momento)
        d["no_ar"] = bool(r["ativo"]) and r["status"] == "pronto" and d["no_periodo"]
        lista.append(d)
    return jsonify(lista)


@app.route("/admin/api/avisos/upload", methods=["POST"])
@login_obrigatorio
def api_avisos_upload():
    arq = request.files.get("arquivo")
    if not arq or not arq.filename:
        return jsonify({"erro": "Nenhum arquivo enviado."}), 400
    nome_original = Path(arq.filename).name[:200]
    ext = Path(nome_original).suffix.lower()
    if ext not in EXT_IMAGEM | EXT_VIDEO:
        return jsonify({"erro": f"Formato {ext or '?'} não aceito. Envie imagem (JPG, PNG, GIF, WEBP) "
                                "ou vídeo (MP4, MOV, WEBM, MKV, AVI)."}), 400

    posicao = "destaque" if request.form.get("posicao") == "destaque" else "carrossel"
    titulo = texto(request.form.get("titulo"))[:200]
    tipo = "video" if ext in EXT_VIDEO else "imagem"
    con = db()
    if posicao == "destaque":      # só um aviso em destaque por vez
        con.execute("UPDATE avisos SET posicao='carrossel' WHERE posicao='destaque'")
    ordem = (con.execute("SELECT COALESCE(MAX(ordem), 0) FROM avisos").fetchone()[0] or 0) + 1
    quando = agora().isoformat(timespec="seconds")
    cur = con.execute(
        "INSERT INTO avisos (titulo, tipo, posicao, ativo, ordem, status, progresso, nome_original, "
        "criado_por, criado_em, atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (titulo, tipo, posicao, 1, ordem, "fila" if tipo == "video" else "processando", 0,
         nome_original, session.get("nome", ""), quando, quando))
    aviso_id = cur.lastrowid
    con.commit()

    temp = TMP_DIR / f"envio_{aviso_id}_{uuid.uuid4().hex}{ext}"
    try:
        arq.save(temp)
        tamanho = temp.stat().st_size
        if tamanho == 0:
            raise ValueError("arquivo vazio")
    except Exception as erro:
        temp.unlink(missing_ok=True)
        con.execute("DELETE FROM avisos WHERE id=?", (aviso_id,))
        con.commit()
        return jsonify({"erro": f"Falha ao receber o arquivo: {erro}"}), 400

    if tipo == "imagem":
        try:
            nome, w, h = processar_imagem(temp, ext)
        except Exception:
            temp.unlink(missing_ok=True)
            con.execute("DELETE FROM avisos WHERE id=?", (aviso_id,))
            con.commit()
            return jsonify({"erro": f"'{nome_original}' não é uma imagem válida."}), 400
        final = MIDIA_DIR / nome
        _atualizar_aviso(con, aviso_id, arquivo=nome, status="pronto", progresso=100,
                         tamanho=final.stat().st_size, largura=w, altura=h)
        gerar_miniatura(aviso_id, final, "imagem")
        registrar(f"Publicou a imagem '{nome_original}'")
    else:
        _atualizar_aviso(con, aviso_id, tamanho=tamanho)
        garantir_trabalhador()
        if CONVERTER_VIDEOS and FFMPEG:
            FILA_VIDEOS.put((aviso_id, str(temp)))
            registrar(f"Enviou o vídeo '{nome_original}' (convertendo para a TV)")
        else:
            converter_video(aviso_id, temp)   # publica na hora, sem conversão
            registrar(f"Publicou o vídeo '{nome_original}'")

    return jsonify(aviso_dict(con.execute("SELECT * FROM avisos WHERE id=?", (aviso_id,)).fetchone()))


@app.route("/admin/api/avisos/<int:aviso_id>", methods=["PUT"])
@login_obrigatorio
def api_avisos_editar(aviso_id):
    con = db()
    r = con.execute("SELECT * FROM avisos WHERE id=?", (aviso_id,)).fetchone()
    if not r:
        return jsonify({"erro": "Aviso não encontrado."}), 404
    d = request.get_json(silent=True) or {}
    campos = {}
    if "titulo" in d:
        campos["titulo"] = texto(d["titulo"])[:200]
    if "descricao" in d:
        campos["descricao"] = texto(d["descricao"])[:1000]
    if "posicao" in d:
        campos["posicao"] = "destaque" if d["posicao"] == "destaque" else "carrossel"
    if "ativo" in d:
        campos["ativo"] = 1 if d["ativo"] else 0
    if "duracao" in d:
        try:
            v = int(d["duracao"]) if texto(d["duracao"]) else None
            campos["duracao"] = max(3, min(600, v)) if v else None
        except (TypeError, ValueError):
            return jsonify({"erro": "Duração inválida."}), 400
    for k in ("inicio", "fim"):
        if k in d:
            v = texto(d[k])
            if v and not ler_data_hora(v):
                return jsonify({"erro": f"Data de {k} inválida."}), 400
            campos[k] = v
    ini, fim = ler_data_hora(campos.get("inicio", r["inicio"])), ler_data_hora(campos.get("fim", r["fim"]))
    if ini and fim and fim < ini:
        return jsonify({"erro": "O fim do período é antes do início."}), 400
    if not campos:
        return jsonify({"erro": "Nada para alterar."}), 400

    # só um aviso em destaque por vez
    if campos.get("posicao") == "destaque":
        con.execute("UPDATE avisos SET posicao='carrossel' WHERE posicao='destaque' AND id<>?", (aviso_id,))
    _atualizar_aviso(con, aviso_id, **campos)
    nome = r["titulo"] or r["nome_original"] or f"#{aviso_id}"
    if list(campos) == ["ativo"]:
        registrar(f"{'Ativou' if campos['ativo'] else 'Pausou'} o aviso '{nome}'")
    else:
        registrar(f"Editou o aviso '{nome}'")
    return jsonify(aviso_dict(con.execute("SELECT * FROM avisos WHERE id=?", (aviso_id,)).fetchone()))


@app.route("/admin/api/avisos/<int:aviso_id>", methods=["DELETE"])
@login_obrigatorio
def api_avisos_apagar(aviso_id):
    con = db()
    r = con.execute("SELECT * FROM avisos WHERE id=?", (aviso_id,)).fetchone()
    if not r:
        return jsonify({"erro": "Aviso não encontrado."}), 404
    con.execute("DELETE FROM avisos WHERE id=?", (aviso_id,))
    con.commit()
    if r["arquivo"]:
        outro = con.execute("SELECT 1 FROM avisos WHERE arquivo=?", (r["arquivo"],)).fetchone()
        if not outro:
            (MIDIA_DIR / r["arquivo"]).unlink(missing_ok=True)
    (THUMB_DIR / f"{aviso_id}.jpg").unlink(missing_ok=True)
    for sobra in TMP_DIR.glob(f"envio_{aviso_id}_*"):
        sobra.unlink(missing_ok=True)
    registrar(f"Excluiu o aviso '{r['titulo'] or r['nome_original'] or aviso_id}'")
    return jsonify({"ok": True})


@app.route("/admin/api/avisos/ordem", methods=["POST"])
@login_obrigatorio
def api_avisos_ordem():
    ids = (request.get_json(silent=True) or {}).get("ids") or []
    con = db()
    for i, aid in enumerate(ids, start=1):
        try:
            con.execute("UPDATE avisos SET ordem=? WHERE id=?", (i, int(aid)))
        except (TypeError, ValueError):
            continue
    con.commit()
    registrar("Reordenou os avisos")
    return jsonify({"ok": True})


# ============================================================
# ADMIN: API - agenda
# ============================================================

@app.route("/admin/api/agenda")
@login_obrigatorio
def api_agenda():
    return jsonify(agenda_atual())


@app.route("/admin/api/agenda/upload", methods=["POST"])
@login_obrigatorio
def api_agenda_upload():
    arq = request.files.get("arquivo")
    if not arq or not arq.filename:
        return jsonify({"erro": "Nenhuma planilha enviada."}), 400
    nome_original = Path(arq.filename).name[:200]
    if Path(nome_original).suffix.lower() not in EXT_PLANILHA:
        return jsonify({"erro": "Envie a planilha no formato Excel (.xlsx)."}), 400
    temp = TMP_DIR / f"agenda_{uuid.uuid4().hex}.xlsx"
    arq.save(temp)
    try:
        reunioes, alertas = ler_planilha_agenda(temp)
    except ValueError as erro:
        temp.unlink(missing_ok=True)
        return jsonify({"erro": str(erro)}), 400
    except Exception as erro:
        temp.unlink(missing_ok=True)
        return jsonify({"erro": f"Não consegui ler a planilha ({erro.__class__.__name__}). "
                                "Confira se é um arquivo .xlsx válido e se não está protegido por senha."}), 400

    # guarda a planilha atual + histórico das 15 últimas
    stamp = agora().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(temp, AGENDA_DIR / f"agenda_{stamp}.xlsx")
    os.replace(temp, AGENDA_XLSX)
    antigas = sorted(AGENDA_DIR.glob("agenda_2*.xlsx"))
    for velha in antigas[:-15]:
        velha.unlink(missing_ok=True)

    dados = {
        "reunioes": reunioes,
        "alertas": alertas,
        "arquivo": nome_original,
        "enviado_em": agora().isoformat(timespec="seconds"),
        "enviado_por": session.get("nome", ""),
    }
    tmp = AGENDA_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, AGENDA_JSON)
    registrar(f"Atualizou a agenda das salas ({len(reunioes)} reuniões) com '{nome_original}'")
    return jsonify(dados)


@app.route("/admin/api/agenda", methods=["DELETE"])
@login_obrigatorio
def api_agenda_limpar():
    dados = {"reunioes": [], "alertas": [], "arquivo": "", "enviado_em": agora().isoformat(timespec="seconds"),
             "enviado_por": session.get("nome", "")}
    AGENDA_JSON.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    registrar("Limpou a agenda das salas")
    return jsonify(dados)


@app.route("/admin/agenda/atual.xlsx")
@login_obrigatorio
def agenda_baixar_atual():
    if not AGENDA_XLSX.exists():
        abort(404)
    nome = agenda_atual().get("arquivo") or "agenda.xlsx"
    return send_file(AGENDA_XLSX, as_attachment=True, download_name=nome)


@app.route("/admin/agenda/modelo.xlsx")
@login_obrigatorio
def agenda_modelo():
    wb = Workbook()
    ws = wb.active
    ws.title = "Salas"
    cab = ["ID", "Sala", "Status", "Responsável", "Data", "Hora Inicial", "Hora Final"]
    ws.append(cab)
    hoje = agora().date()
    exemplos = [
        (1, "Reunião Time Contábil", "RESERVADA", "Presença", hoje, dtime(9, 0), dtime(10, 0)),
        (2, "Sala de Reuniões 1 - Cliente XPTO", "RESERVADA", "Wallace", hoje + timedelta(days=1), dtime(14, 0), dtime(15, 30)),
        (3, "Treinamento DP", "OCUPADA", "RH", hoje, dtime(15, 0), dtime(17, 0)),
    ]
    for e in exemplos:
        ws.append(e)
    laranja = PatternFill("solid", fgColor="FF5A0A")
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = laranja
        c.alignment = Alignment(horizontal="center")
    for linha in ws.iter_rows(min_row=2):
        linha[4].number_format = "DD/MM/YYYY"
        linha[5].number_format = "HH:MM"
        linha[6].number_format = "HH:MM"
    for col, larg in zip("ABCDEFG", (6, 38, 14, 20, 13, 13, 13)):
        ws.column_dimensions[col].width = larg
    ws.freeze_panes = "A2"
    from openpyxl.worksheet.datavalidation import DataValidation
    dv = DataValidation(type="list", formula1='"RESERVADA,OCUPADA,DISPONIVEL"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("C2:C500")
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="modelo_agenda_salas.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ============================================================
# ADMIN: API - atendimento / configurações / usuários
# ============================================================

@app.route("/admin/api/atendimento")
@login_obrigatorio
def api_admin_atendimento():
    d = atendimento_ler()
    idade = int(time.time() - float(d.get("recebido_ts") or 0)) if d else None
    return jsonify({"tv": atendimento_para_tv(), "ultimo_contato_s": idade,
                    "token": cfg("leitor_token"), "url_push": _endereco_publico()})


LEITOR_DIR = BASE_DIR / "leitor_local"
LEITOR_ARQUIVOS = ("INSTALAR.bat", "instalador.ps1", "COMO INSTALAR.txt", "leitor_messenger.py",
                   "config.ini", "iniciar_leitor.bat", "login_messenger.bat", "instalar.bat")


def _endereco_publico():
    """Endereço do painel como o leitor deve usar (https quando há proxy na frente)."""
    url = request.host_url.rstrip("/")
    https_na_frente = (request.headers.get("X-Forwarded-Proto", "").lower() == "https"
                       or request.host.endswith(".pythonanywhere.com"))
    if url.startswith("http://") and https_na_frente:
        url = "https://" + url[len("http://"):]
    return url


@app.route("/admin/leitor/instalador.zip")
@login_obrigatorio
def leitor_baixar_instalador():
    """Zip do leitor do Messenger já com o endereço e o token deste painel."""
    import zipfile
    if not (LEITOR_DIR / "leitor_messenger.py").exists():
        return ("A pasta leitor_local não está neste servidor. Envie a pasta leitor_local "
                "junto com o app.py para liberar o download do instalador."), 404
    url, token = _endereco_publico(), cfg("leitor_token")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nome in LEITOR_ARQUIVOS:
            arq = LEITOR_DIR / nome
            if not arq.exists():
                continue
            if nome == "config.ini":
                conteudo = arq.read_text(encoding="utf-8-sig")
                conteudo = re.sub(r"(?m)^url\s*=.*$", "url   = " + url, conteudo, count=1)
                conteudo = re.sub(r"(?m)^token\s*=.*$", "token = " + token, conteudo, count=1)
                z.writestr("LeitorMessenger/config.ini", "\ufeff" + conteudo)
            else:
                z.write(arq, "LeitorMessenger/" + nome)
    buf.seek(0)
    resp = send_file(buf, as_attachment=True, download_name="LeitorMessenger.zip", mimetype="application/zip")
    resp.headers["Cache-Control"] = "no-store"
    return resp


LEITOR_EXE = LEITOR_DIR / "dist" / "InstalarLeitorMessenger.exe"


@app.route("/admin/leitor/instalador.exe")
@login_obrigatorio
def leitor_baixar_exe():
    """Instalador .exe do leitor com o endereço e o token deste painel no fim do arquivo.
    O .exe lê esse trecho ao rodar (leitor_local/instalador_exe/main.go)."""
    import base64
    if not LEITOR_EXE.exists():
        return ("O arquivo leitor_local/dist/InstalarLeitorMessenger.exe não está neste servidor. "
                "Envie a pasta leitor_local junto com o app.py."), 404
    cfg_json = json.dumps({"url": _endereco_publico(), "token": cfg("leitor_token")})
    trailer = b"\nLEITORCFG1:" + base64.b64encode(cfg_json.encode("utf-8")) + b":FIM\n"
    buf = BytesIO(LEITOR_EXE.read_bytes() + trailer)
    resp = send_file(buf, as_attachment=True, download_name="InstalarLeitorMessenger.exe",
                     mimetype="application/vnd.microsoft.portable-executable")
    resp.headers["Cache-Control"] = "no-store"
    return resp


EXTENSAO_DIR = BASE_DIR / "leitor_extensao"
EXTENSAO_ARQUIVOS = ("manifest.json", "background.js", "conteudo.js", "opcoes.html", "opcoes.js",
                     "config.js", "COMO INSTALAR.txt")


@app.route("/admin/leitor/extensao.zip")
@login_obrigatorio
def leitor_baixar_extensao():
    """Extensão do Chrome que lê o Messenger no navegador do atendente,
    já com o endereço e o token deste painel."""
    import zipfile
    if not (EXTENSAO_DIR / "manifest.json").exists():
        return "A pasta leitor_extensao não está neste servidor. Envie-a junto com o app.py.", 404
    url, token = _endereco_publico(), cfg("leitor_token")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nome in EXTENSAO_ARQUIVOS:
            arq = EXTENSAO_DIR / nome
            if not arq.exists():
                continue
            destino = "LeitorMessengerChrome/" + nome
            if nome == "config.js":
                z.writestr(destino, "self.PAINEL_CONFIG = " + json.dumps({"url": url, "token": token}) + ";\n")
            elif nome == "manifest.json":
                manifesto = json.loads(arq.read_text(encoding="utf-8"))
                manifesto["host_permissions"] = ["https://app.gestta.com.br/*", url + "/*"]
                z.writestr(destino, json.dumps(manifesto, ensure_ascii=False, indent=2))
            else:
                z.write(arq, destino)
    buf.seek(0)
    resp = send_file(buf, as_attachment=True, download_name="LeitorMessengerChrome.zip", mimetype="application/zip")
    resp.headers["Cache-Control"] = "no-store"
    return resp


CHAVES_EDITAVEIS = {"empresa_titulo", "empresa_subtitulo", "rodape", "tempo_imagem", "mostrar_atendimento",
                    "max_clientes_card", "ocultar_reunioes_passadas",
                    "alerta_ativo", "alerta_card", "alerta_som", "alerta_voz", "alerta_volume",
                    "alerta_duracao", "alerta_repetir_min"}
CHAVES_SIM_NAO = {"mostrar_atendimento", "ocultar_reunioes_passadas",
                  "alerta_ativo", "alerta_card", "alerta_som", "alerta_voz"}
LIMITES_NUM = {"tempo_imagem": (1, 600), "max_clientes_card": (1, 8), "alerta_volume": (0, 100),
               "alerta_duracao": (4, 120), "alerta_repetir_min": (0, 240)}


@app.route("/admin/api/config", methods=["GET", "PUT"])
@login_obrigatorio
def api_config():
    if request.method == "PUT":
        d = request.get_json(silent=True) or {}
        con = db()
        for k, v in d.items():
            if k not in CHAVES_EDITAVEIS:
                continue
            if k in LIMITES_NUM:
                minimo, maximo = LIMITES_NUM[k]
                try:
                    v = max(minimo, min(maximo, int(v)))
                except (TypeError, ValueError):
                    return jsonify({"erro": f"Valor inválido em {k}."}), 400
            if k in CHAVES_SIM_NAO:
                v = "sim" if v in (True, "sim", "1", 1, "true") else "nao"
            cfg_salvar(k, texto(v)[:300], con)
        con.commit()
        registrar("Alterou as configurações do painel")
    c = cfg_todas()
    c["tv_url"] = request.host_url.rstrip("/") + "/" + (f"?chave={c['tv_chave']}" if c.get("tv_chave") else "")
    return jsonify(c)


@app.route("/admin/api/alerta/teste", methods=["POST"])
@login_obrigatorio
def api_alerta_teste():
    """As TVs abertas tocam um alerta de exemplo em até 4 segundos."""
    cfg_salvar("alerta_teste", str(int(time.time())))
    registrar("Testou o alerta de atendimento nas TVs")
    return jsonify({"ok": True})


@app.route("/admin/api/config/tv-chave", methods=["POST"])
@login_obrigatorio
def api_tv_chave():
    acao = (request.get_json(silent=True) or {}).get("acao")
    nova = "" if acao == "remover" else secrets.token_urlsafe(12)
    cfg_salvar("tv_chave", nova)
    registrar("Removeu a chave de acesso da TV" if not nova else "Gerou nova chave de acesso da TV")
    return api_config()


@app.route("/admin/api/config/leitor-token", methods=["POST"])
@login_obrigatorio
def api_leitor_token():
    cfg_salvar("leitor_token", secrets.token_urlsafe(32))
    registrar("Gerou novo token do leitor do Messenger")
    return api_admin_atendimento()


@app.route("/admin/api/usuarios", methods=["GET", "POST"])
@login_obrigatorio
def api_usuarios():
    con = db()
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        login = texto(d.get("login")).lower()
        senha = d.get("senha") or ""
        if not re.match(r"^[a-z0-9._-]{3,40}$", login):
            return jsonify({"erro": "Usuário: 3 a 40 letras minúsculas, números, ponto, hífen ou _."}), 400
        if len(senha) < 8:
            return jsonify({"erro": "A senha precisa ter pelo menos 8 caracteres."}), 400
        try:
            con.execute("INSERT INTO usuarios (login, nome, senha_hash, criado_em) VALUES (?,?,?,?)",
                        (login, texto(d.get("nome"))[:80] or login, generate_password_hash(senha),
                         agora().isoformat(timespec="seconds")))
            con.commit()
        except sqlite3.IntegrityError:
            return jsonify({"erro": "Já existe um usuário com esse login."}), 400
        registrar(f"Criou o usuário '{login}'")
    lista = [dict(r) for r in con.execute("SELECT id, login, nome, criado_em FROM usuarios ORDER BY login")]
    for u in lista:
        u["voce"] = u["id"] == session.get("uid")
    return jsonify(lista)


@app.route("/admin/api/usuarios/<int:uid>", methods=["DELETE"])
@login_obrigatorio
def api_usuarios_apagar(uid):
    if uid == session.get("uid"):
        return jsonify({"erro": "Você não pode excluir o próprio usuário."}), 400
    con = db()
    u = con.execute("SELECT login FROM usuarios WHERE id=?", (uid,)).fetchone()
    if not u:
        return jsonify({"erro": "Usuário não encontrado."}), 404
    con.execute("DELETE FROM usuarios WHERE id=?", (uid,))
    con.commit()
    registrar(f"Excluiu o usuário '{u['login']}'")
    return jsonify({"ok": True})


@app.route("/admin/api/senha", methods=["POST"])
@login_obrigatorio
def api_trocar_senha():
    d = request.get_json(silent=True) or {}
    con = db()
    u = con.execute("SELECT * FROM usuarios WHERE id=?", (session["uid"],)).fetchone()
    if not u or not check_password_hash(u["senha_hash"], d.get("atual") or ""):
        return jsonify({"erro": "Senha atual incorreta."}), 400
    nova = d.get("nova") or ""
    if len(nova) < 8:
        return jsonify({"erro": "A nova senha precisa ter pelo menos 8 caracteres."}), 400
    con.execute("UPDATE usuarios SET senha_hash=? WHERE id=?", (generate_password_hash(nova), u["id"]))
    con.commit()
    (DATA_DIR / "SENHA_INICIAL_ADMIN.txt").unlink(missing_ok=True)
    registrar("Trocou a própria senha")
    return jsonify({"ok": True})


@app.route("/admin/api/historico")
@login_obrigatorio
def api_historico():
    return jsonify([dict(r) for r in db().execute("SELECT * FROM historico ORDER BY id DESC LIMIT 100")])


@app.errorhandler(413)
def muito_grande(_e):
    return jsonify({"erro": f"Arquivo maior que o limite de {MAX_UPLOAD_MB} MB."}), 413


# ============================================================
# MIGRAÇÃO DA VERSÃO ANTIGA (pasta local + planilha da rede)
#   python app.py importar "C:\caminho\Avisos" ["Z:\...\avisos.xlsx"]
# ============================================================

def importar_versao_antiga(pasta_antiga, planilha=None):
    pasta = Path(pasta_antiga)
    planilha = Path(planilha) if planilha else pasta / "dados" / "avisos.xlsx"
    midia_antiga = pasta / "static" / "avisos"
    if not planilha.exists():
        print("Planilha não encontrada:", planilha)
        return
    print("Lendo", planilha)
    with app.app_context():
        con = db()
        wb = load_workbook(planilha, data_only=True)
        if "Avisos" in wb.sheetnames:
            linhas = list(wb["Avisos"].iter_rows(values_only=True))
            cab = [normalizar(c) for c in linhas[0]]

            def col(*nomes):
                for n in nomes:
                    if normalizar(n) in cab:
                        return cab.index(normalizar(n))
                return None
            c_arq, c_tit, c_desc = col("Imagem", "Arquivo", "Midia"), col("Título", "Titulo"), col("Descrição", "Descricao")
            c_at, c_ord, c_pos = col("Ativo"), col("Ordem"), col("Posição", "Posicao")
            for linha in linhas[1:]:
                arquivo = texto(linha[c_arq]) if c_arq is not None else ""
                origem = midia_antiga / arquivo
                if not arquivo or not origem.exists():
                    if arquivo:
                        print("  ⚠ arquivo não encontrado:", origem)
                    continue
                ext = origem.suffix.lower()
                tipo = "video" if ext in EXT_VIDEO else "imagem"
                quando = agora().isoformat(timespec="seconds")
                pos = "destaque" if normalizar(linha[c_pos] if c_pos is not None else "") in {"card1", "card", "destaque"} else "carrossel"
                try:
                    ordem = int(linha[c_ord]) if c_ord is not None and linha[c_ord] is not None else 9999
                except (TypeError, ValueError):
                    ordem = 9999
                cur = con.execute(
                    "INSERT INTO avisos (titulo, descricao, tipo, posicao, ativo, ordem, status, progresso, "
                    "nome_original, criado_por, criado_em, atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (texto(linha[c_tit]) if c_tit is not None else "", texto(linha[c_desc]) if c_desc is not None else "",
                     tipo, pos, 1 if sim(linha[c_at] if c_at is not None else "sim") else 0, ordem,
                     "fila", 0, arquivo, "importação", quando, quando))
                con.commit()
                temp = TMP_DIR / f"envio_{cur.lastrowid}_{uuid.uuid4().hex}{ext}"
                shutil.copy2(origem, temp)
                if tipo == "video":
                    converter_video(cur.lastrowid, temp)
                else:
                    nome, w, h = processar_imagem(temp, ext)
                    _atualizar_aviso(con, cur.lastrowid, arquivo=nome, status="pronto", progresso=100,
                                     tamanho=(MIDIA_DIR / nome).stat().st_size, largura=w, altura=h)
                    gerar_miniatura(cur.lastrowid, MIDIA_DIR / nome, "imagem")
                print("  ✔ aviso importado:", arquivo)
        wb.close()
        reunioes, alertas = ler_planilha_agenda(planilha)
        shutil.copy2(planilha, AGENDA_XLSX)
        AGENDA_JSON.write_text(json.dumps({
            "reunioes": reunioes, "alertas": alertas, "arquivo": planilha.name,
            "enviado_em": agora().isoformat(timespec="seconds"), "enviado_por": "importação"},
            ensure_ascii=False), encoding="utf-8")
        print(f"  ✔ agenda importada: {len(reunioes)} reunião(ões)")
        registrar("Importou os dados da versão antiga", "sistema", con)
        con.commit()


# ============================================================
# INICIALIZAÇÃO
# ============================================================

iniciar_banco()
garantir_trabalhador()

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "importar":
        importar_versao_antiga(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
        sys.exit(0)
    porta = int(os.environ.get("PORTA", "5000"))
    print("=" * 55)
    print(f" Painel:  http://localhost:{porta}/")
    print(f" Admin:   http://localhost:{porta}/admin")
    print(f" Dados:   {DATA_DIR}")
    print(f" FFmpeg:  {'OK' if FFMPEG else 'NÃO encontrado (vídeos não serão convertidos)'}")
    print("=" * 55)
    app.run(host="0.0.0.0", port=porta, debug=False, threaded=True)
