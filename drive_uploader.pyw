# -*- coding: utf-8 -*-
"""Drive: enviar e baixar - interface para o rclone (varias contas Google).

Envia pastas/arquivos para o Google Drive e baixa pastas/arquivos por link,
direto no disco, sem cache e sem compactar.
Tudo fica nesta pasta: rclone.exe, rclone.conf (contas), libs e uploader_settings.json.
"""
import json
import os
import queue
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from tkinter import filedialog, messagebox

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "libs"))
import customtkinter as ctk  # noqa: E402

APP_NAME = "Drive Enviar e Baixar"
APP_VERSION = "1.2.1"
DEV_HANDLE = "@digao.fpv"
DEV_URL = "https://instagram.com/digao.fpv"
REPO_URL = "https://github.com/digaofpv/drive-enviar-baixar"

def _load_env(path):
    """Le um arquivo .env simples (CHAVE=valor) para as variaveis de ambiente."""
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


_load_env(os.path.join(BASE, ".env"))

# Doacao por Pix (opcional). Sem PIX_KEY (no .env ou no ambiente), o botao "Apoiar" nao aparece.
PIX_KEY = os.environ.get("PIX_KEY", "").strip() or "d03514da-0d0b-4faf-a602-9535738eb698"  # chave aleatoria (publica, para doacoes)
PIX_NAME = "DIGAO FPV"                              # nome exibido no QR (o banco mostra o titular real)
PIX_CITY = "CURITIBA"                               # cidade do titular (ate 15 letras)
PIX_VALUE = "10.00"                                 # valor sugerido no QR

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
UI = "Segoe UI" if IS_WIN else ("Helvetica Neue" if IS_MAC else "DejaVu Sans")
MONO = "Consolas" if IS_WIN else ("Menlo" if IS_MAC else "DejaVu Sans Mono")

RCLONE = os.path.join(BASE, "rclone.exe" if IS_WIN else "rclone")
CONF = os.path.join(BASE, "rclone.conf")
SETTINGS = os.path.join(BASE, "uploader_settings.json")
ICON = os.path.join(BASE, "icone.ico")
ICON_PNG = os.path.join(BASE, "icone.png")
_icon_img = []

try:  # certificados para HTTPS (o Python do python.org no Mac nao usa os do sistema)
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = ssl.create_default_context()


def set_icon(win):
    """Aplica o icone do programa (com atraso, senao a biblioteca visual troca pelo dela)."""
    def apply():
        try:
            if not win.winfo_exists():
                return
            if IS_WIN and os.path.exists(ICON):
                win.iconbitmap(ICON)
            elif os.path.exists(ICON_PNG):  # Mac: tambem troca o icone do Dock
                if not _icon_img:
                    _icon_img.append(tk.PhotoImage(file=ICON_PNG))
                win.iconphoto(True, _icon_img[0])
        except Exception:
            pass
    win.after(300, apply)


NOWIN = 0x08000000 if IS_WIN else 0  # Windows: nao abrir janela preta de console
FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
MAX_ROWS = 4  # linhas de "arquivos em andamento" mostradas na tela
LOG_MAX = 400  # linhas guardadas no registro (mais que isso deixa a janela pesada)
DEFAULTS = {"transfers": 4, "bw_up": 0, "bw_down": 0}  # 0 = sem limite (MB/s)

# cores
BG = "#14171c"
CARD = "#1d2229"
CARD2 = "#252b34"
ACCENT = "#3b82f6"
ACCENT_H = "#2563eb"
GREEN = "#22c55e"
RED = "#ef4444"
MUTED = "#8b95a5"
TEXT = "#e6e9ee"


# ------------------------------------------------------------------ rclone
def rclone(args, timeout=None):
    return subprocess.run(
        [RCLONE, "--config", CONF] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, creationflags=NOWIN, timeout=timeout)


def access_token(name):
    dump = json.loads(rclone(["config", "dump"], timeout=30).stdout)
    return json.loads(dump[name]["token"])["access_token"]


def drive_api(name, path, headers=None):
    """Consulta simples a API do Google Drive usando o login ja salvo da conta."""
    url = "https://www.googleapis.com/drive/v3/" + path
    for attempt in range(1, 6):
        h = {"Authorization": "Bearer " + access_token(name)}
        h.update(headers or {})
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30,
                                        context=SSL_CTX) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code == 401 and attempt == 1:
                r = rclone(["about", name + ":"], timeout=120)  # renova o login vencido
                if r.returncode != 0 and "invalid_grant" in (r.stderr or ""):
                    raise LoginExpired(name)  # o Google nao renova mais: precisa logar de novo
                continue
            flat = body.lower().replace("_", "")
            limited = e.code in (429, 500, 502, 503) or (
                e.code == 403 and ("ratelimit" in flat or "quota exceeded" in flat))
            if limited and attempt < 5:
                time.sleep(2 * attempt)  # Google pediu para ir mais devagar: espera e tenta de novo
                continue
            if limited:
                raise RateLimited()
            raise


class RateLimited(Exception):
    """O Google recusou por excesso de consultas (limite do login compartilhado do rclone)."""


class LoginExpired(Exception):
    """O login salvo da conta expirou ou foi revogado (invalid_grant): precisa reconectar."""


def account_email(name):
    return drive_api(name, "about?fields=user(emailAddress)")["user"]["emailAddress"]


def parse_link(text):
    """Extrai o ID (e a resourcekey, se houver) de um link do Google Drive."""
    text = (text or "").strip()
    m = (re.search(r"/folders/([A-Za-z0-9_-]{10,})", text)
         or re.search(r"/d/([A-Za-z0-9_-]{10,})", text)
         or re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", text))
    fid = m.group(1) if m else (text if re.fullmatch(r"[A-Za-z0-9_-]{15,}", text) else None)
    rk = re.search(r"resourcekey=([A-Za-z0-9_-]+)", text)
    return fid, (rk.group(1) if rk else None)


def file_meta(name, fid, rk=None):
    headers = {"X-Goog-Drive-Resource-Keys": f"{fid}/{rk}"} if rk else None
    q = "?fields=id,name,mimeType,size,shortcutDetails&supportsAllDrives=true"
    meta = drive_api(name, "files/" + fid + q, headers)
    if meta.get("mimeType") == SHORTCUT_MIME and meta.get("shortcutDetails", {}).get("targetId"):
        meta = drive_api(name, "files/" + meta["shortcutDetails"]["targetId"] + q)
    return meta


# -------------------------------------------------------------- formatacao
def fmt_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.2f} {unit}"
        n /= 1024


def fmt_speed(n):
    return fmt_bytes(n) + "/s" if n else "--"


def fmt_time(s):
    if s is None:
        return "--"
    s = int(s)
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    if h:
        return f"{h}h {m:02d}min"
    if m:
        return f"{m}min {sec:02d}s"
    return f"{sec}s"


def safe_name(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name or "").strip(" .") or "download"


def local_size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def free_space(path):
    p = os.path.abspath(path)
    while p and not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    try:
        return shutil.disk_usage(p).free
    except Exception:
        return None


# ------------------------------------------------------------------ Pix
def _crc16(data):
    crc = 0xFFFF
    for b in data.encode("utf-8"):
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def _plain(text, size):
    import unicodedata
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9 .\-]", "", t).strip()[:size]


def pix_payload(key, name, city, value=None, txid="***"):
    """Codigo Pix 'copia e cola' (BR Code estatico do Banco Central)."""
    def f(i, v):
        return f"{i}{len(v):02d}{v}"
    acc = f("00", "br.gov.bcb.pix") + f("01", key.strip())
    p = f("00", "01") + f("26", acc) + f("52", "0000") + f("53", "986")
    if value:
        p += f("54", value)
    p += f("58", "BR") + f("59", _plain(name, 25)) + f("60", _plain(city, 15)) + f("62", f("05", txid))
    p += "6304"
    return p + _crc16(p)


PARTIAL_RE = re.compile(r"\.[0-9a-fA-F]{8}\.partial$")  # nome provisorio do rclone: arquivo.ext.1a2b3c4d.partial


def find_partials(root):
    """Arquivos incompletos deixados pelo rclone (downloads interrompidos)."""
    out = []
    if not root or not os.path.isdir(root):
        return out
    for r, _, files in os.walk(root):
        for f in files:
            if PARTIAL_RE.search(f):
                p = os.path.join(r, f)
                try:
                    out.append((p, os.path.getsize(p)))
                except OSError:
                    pass
    return out


def delete_files(items):
    ok, freed = 0, 0
    for p, size in items:
        try:
            os.remove(p)
            ok += 1
            freed += size
        except OSError:
            pass
    return ok, freed


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(data):
    try:
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def btn(parent, text, command, kind="normal", **kw):
    colors = {
        "normal": dict(fg_color=CARD2, hover_color="#313948", text_color=TEXT),
        "primary": dict(fg_color=ACCENT, hover_color=ACCENT_H, text_color="white"),
        "danger": dict(fg_color="#3a2326", hover_color="#5a2a2e", text_color="#ffb4b4"),
    }[kind]
    return ctk.CTkButton(parent, text=text, command=command, corner_radius=8, **colors, **kw)


# ------------------------------------------------------- navegar no Drive
class BrowseDialog(ctk.CTkToplevel):
    """Navega pelas pastas do Drive para escolher o destino do envio."""

    def __init__(self, app, remote, start, shared):
        super().__init__(app)
        self.title(f"Escolher pasta no Drive ({remote})")
        set_icon(self)
        self.geometry("540x480")
        self.configure(fg_color=BG)
        self.transient(app)
        self.remote, self.shared = remote, shared
        self.path = start.strip("/")
        self.result = None
        self.token = 0
        self.dirs = []

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(12, 6))
        btn(top, "⬆  Acima", self.up, width=90).pack(side="left")
        self.lbl = ctk.CTkLabel(top, text="", font=(UI, 13, "bold"), text_color=TEXT)
        self.lbl.pack(side="left", padx=10)

        mid = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10)
        mid.pack(fill="both", expand=True, padx=12)
        self.lb = tk.Listbox(mid, activestyle="none", font=(UI, 11), bg=CARD, fg=TEXT,
                             selectbackground=ACCENT, selectforeground="white",
                             highlightthickness=0, borderwidth=0)
        self.lb.pack(fill="both", expand=True, padx=8, pady=8)
        self.lb.bind("<Double-Button-1>", lambda e: self.enter())

        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.pack(fill="x", padx=12, pady=12)
        ctk.CTkLabel(bot, text="Duplo clique entra na pasta.", text_color=MUTED).pack(side="left")
        btn(bot, "Usar esta pasta", self.choose, "primary", width=140).pack(side="right")
        btn(bot, "Cancelar", self.destroy, width=90).pack(side="right", padx=8)

        self.load()
        self.after(200, self._focus)

    def _focus(self):
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
        except Exception:
            pass

    def load(self):
        self.token += 1
        tok = self.token
        self.lbl.configure(text="/" + self.path if self.path else "/ (raiz do Drive)")
        self.lb.delete(0, "end")
        self.lb.insert("end", "carregando...")
        self.dirs = []
        path = self.path

        def work():
            args = ["lsf", "--dirs-only", f"{self.remote}:{path}"]
            if self.shared:
                args.append("--drive-shared-with-me")
            try:
                r = rclone(args, timeout=120)
                dirs = sorted((d.rstrip("/") for d in r.stdout.splitlines() if d.strip()),
                              key=str.lower)
                err = r.stderr.strip() if r.returncode else ""
            except Exception as e:
                dirs, err = [], str(e)
            self.after(0, lambda: self.show(tok, dirs, err))

        threading.Thread(target=work, daemon=True).start()

    def show(self, tok, dirs, err):
        if tok != self.token or not self.winfo_exists():
            return
        self.lb.delete(0, "end")
        if err:
            self.lb.insert("end", "(erro ao listar)")
            messagebox.showerror("Erro", err[-600:], parent=self)
            return
        if not dirs:
            self.lb.insert("end", "(nenhuma subpasta)")
            return
        self.dirs = dirs
        for d in dirs:
            self.lb.insert("end", "📁  " + d)

    def enter(self):
        sel = self.lb.curselection()
        if not sel or not self.dirs:
            return
        self.path = (self.path + "/" + self.dirs[sel[0]]).strip("/")
        self.load()

    def up(self):
        if self.path:
            self.path = self.path.rsplit("/", 1)[0] if "/" in self.path else ""
            self.load()

    def choose(self):
        sel = self.lb.curselection()
        path = self.path
        if sel and self.dirs:
            path = (path + "/" + self.dirs[sel[0]]).strip("/")
        self.result = path
        self.destroy()


# ------------------------------------------------------------------- app
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME}  v{APP_VERSION}")
        set_icon(self)
        h = min(930, self.winfo_screenheight() - 90)  # cabe em telas menores (ex.: MacBook Air)
        self.geometry(f"960x{h}")
        self.minsize(860, min(800, h))
        self.configure(fg_color=BG)
        self.settings = load_settings()
        self.q = queue.Queue()
        self.proc = None
        self.auth_proc = None
        self.running = False
        self.cancel = False
        self.items = []
        self.meta = None          # dados do link verificado
        self.meta_token = 0
        self.pending_download = False
        self.open_path = None
        self.job_info = ""
        self._last = {}       # ultimo valor de cada texto/barra (so redesenha o que mudou)
        self._logbuf = []     # linhas do registro esperando para entrar de uma vez

        self.build_header()
        self.build_tabs()
        self.build_progress()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if not os.path.exists(RCLONE):
            messagebox.showerror("rclone", f"Nao achei o rclone em:\n{RCLONE}")
        self.refresh_remotes(self.settings.get("last_remote"))
        self.after(150, self.poll)

    # ------------------------------------------------------------ montagem
    def build_header(self):
        # faixa do topo: nome, versao, desenvolvedor e "Sobre"
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(10, 0))
        ctk.CTkLabel(top, text=APP_NAME, font=(UI, 16, "bold"), text_color=TEXT).pack(side="left")
        ctk.CTkLabel(top, text=f"v{APP_VERSION}", font=(UI, 11, "bold"), text_color=ACCENT,
                     fg_color=CARD2, corner_radius=6, width=44, height=20).pack(side="left", padx=8)
        ctk.CTkButton(top, text="ⓘ  Sobre", command=self.about_dialog, width=74, height=26,
                      fg_color="transparent", hover_color=CARD2, text_color=MUTED,
                      font=(UI, 12), corner_radius=6).pack(side="right")
        self.btn_cfg = ctk.CTkButton(top, text="⚙  Configurações", command=self.settings_dialog, width=120,
                                     height=26, fg_color="transparent", hover_color=CARD2, text_color=MUTED,
                                     font=(UI, 12), corner_radius=6)
        self.btn_cfg.pack(side="right", padx=(0, 4))
        dev = ctk.CTkLabel(top, text=f"desenvolvido por {DEV_HANDLE}", font=(UI, 12, "underline"),
                           text_color=MUTED, cursor="hand2")
        dev.pack(side="right", padx=10)
        dev.bind("<Button-1>", lambda e: webbrowser.open(DEV_URL))

        f = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        f.pack(fill="x", padx=14, pady=(8, 6))
        ctk.CTkLabel(f, text="Conta", font=(UI, 13, "bold"), text_color=MUTED
                     ).pack(side="left", padx=(16, 8), pady=14)
        self.om_remote = ctk.CTkOptionMenu(
            f, values=[""], command=lambda v: self.on_remote(), width=230, height=34,
            fg_color=CARD2, button_color=ACCENT, button_hover_color=ACCENT_H,
            dropdown_fg_color=CARD2, font=(UI, 14, "bold"), corner_radius=8)
        self.om_remote.pack(side="left")
        self.lbl_email = ctk.CTkLabel(f, text="", text_color=MUTED, font=(UI, 12))
        self.lbl_email.pack(side="left", padx=12)
        self.btn_del = btn(f, "Remover", self.del_account, "danger", width=84)
        self.btn_del.pack(side="right", padx=(6, 14))
        self.btn_rec = btn(f, "↻  Reconectar", self.reconnect_account, width=110)
        self.btn_rec.pack(side="right", padx=(6, 0))
        self.btn_add = btn(f, "+  Adicionar conta", self.add_account, width=140)
        self.btn_add.pack(side="right")
        self.btn_key = btn(f, "", self.key_dialog, width=120)
        self.btn_key.pack(side="right", padx=6)
        self.update_key_button()

    def about_dialog(self):
        d = ctk.CTkToplevel(self)
        d.title("Sobre")
        set_icon(d)
        d.geometry("460x470")
        d.resizable(False, False)
        d.configure(fg_color=BG)
        d.transient(self)
        if os.path.exists(ICON_PNG):
            try:
                img = tk.PhotoImage(file=ICON_PNG)
                img = img.subsample(max(1, img.width() // 88))
                d._img = img
                tk.Label(d, image=img, bg=BG, borderwidth=0).pack(pady=(22, 6))
            except Exception:
                pass
        ctk.CTkLabel(d, text=APP_NAME, font=(UI, 20, "bold"), text_color=TEXT).pack()
        ctk.CTkLabel(d, text=f"Versão {APP_VERSION}", font=(UI, 13), text_color=MUTED).pack(pady=(2, 12))
        ctk.CTkLabel(d, text="Envia e baixa pastas do Google Drive direto no disco,\nsem cache e sem compactar.",
                     font=(UI, 12), text_color=TEXT, justify="center").pack(pady=(0, 14))

        def link(text, url, size=13, bold=False):
            lb = ctk.CTkLabel(d, text=text, font=(UI, size, "bold" if bold else "normal"), text_color=ACCENT,
                              cursor="hand2")
            lb.pack(pady=2)
            lb.bind("<Button-1>", lambda e: webbrowser.open(url))

        ctk.CTkLabel(d, text="Desenvolvido por", font=(UI, 11), text_color=MUTED).pack()
        link(f"{DEV_HANDLE}  (Instagram)", DEV_URL, 15, True)
        link("Código e atualizações no GitHub", REPO_URL, 12)
        rc_ver = ""
        try:
            rc_ver = rclone(["version"], timeout=15).stdout.splitlines()[0].strip()
        except Exception:
            pass
        ctk.CTkLabel(d, text=f"Transferências feitas pelo {rc_ver or 'rclone'} (rclone.org)  ·  licença MIT",
                     font=(UI, 10), text_color=MUTED).pack(pady=(14, 0))
        row = ctk.CTkFrame(d, fg_color="transparent")
        row.pack(pady=14)
        if PIX_KEY:
            btn(row, "♥  Apoiar o projeto", lambda: (d.destroy(), self.donate_dialog()), "primary",
                width=170).pack(side="left", padx=6)
        btn(row, "Fechar", d.destroy, width=100).pack(side="left", padx=6)
        d.after(200, lambda: (d.lift(), d.focus_force()))

    def donate_dialog(self):
        d = ctk.CTkToplevel(self)
        d.title("Apoiar o projeto")
        set_icon(d)
        d.geometry("420x560")
        d.resizable(False, False)
        d.configure(fg_color=BG)
        d.transient(self)
        valor = PIX_VALUE.replace(".", ",")
        ctk.CTkLabel(d, text="Gostou do app?", font=(UI, 20, "bold"), text_color=TEXT).pack(pady=(22, 2))
        ctk.CTkLabel(d, text=f"Ele é gratuito. Se ele te poupou tempo, considere\napoiar com um Pix de R$ {valor}.",
                     font=(UI, 12), text_color=MUTED, justify="center").pack(pady=(0, 14))
        code = pix_payload(PIX_KEY, PIX_NAME, PIX_CITY, PIX_VALUE)
        try:
            import qrcode
            qr = qrcode.QRCode(border=3, error_correction=qrcode.constants.ERROR_CORRECT_M)
            qr.add_data(code)
            qr.make(fit=True)
            mtx = qr.get_matrix()
            px = max(3, 230 // len(mtx))
            side = px * len(mtx)
            cv = tk.Canvas(d, width=side, height=side, bg="white", highlightthickness=0)
            for y, line in enumerate(mtx):
                for x, on in enumerate(line):
                    if on:
                        cv.create_rectangle(x * px, y * px, x * px + px, y * px + px, fill="black", width=0)
            cv.pack(pady=(0, 6))
            ctk.CTkLabel(d, text=f"Aponte a câmera do app do banco  ·  R$ {valor}",
                         font=(UI, 11), text_color=MUTED).pack(pady=(0, 12))
        except Exception:
            pass

        def copiar(texto, aviso):
            self.clipboard_clear()
            self.clipboard_append(texto)
            msg.configure(text=aviso)

        btn(d, f"Copiar Pix copia e cola (R$ {valor})", lambda: copiar(code, "Código copiado: cole no app do banco."),
            "primary", width=280).pack(pady=3)
        btn(d, "Copiar só a chave (qualquer valor)", lambda: copiar(PIX_KEY, "Chave copiada."),
            width=280).pack(pady=3)
        msg = ctk.CTkLabel(d, text="", font=(UI, 11), text_color=GREEN)
        msg.pack(pady=(6, 0))
        ctk.CTkLabel(d, text=f"Obrigado!  {DEV_HANDLE}", font=(UI, 12, "bold"), text_color=TEXT).pack(pady=(6, 0))
        d.after(200, lambda: (d.lift(), d.focus_force()))

    def cfg(self, key):
        try:
            return int(self.settings.get(key, DEFAULTS[key]))
        except (TypeError, ValueError):
            return DEFAULTS[key]

    def settings_dialog(self):
        if self.busy():
            messagebox.showinfo("Configurações", "Espere a transferência atual terminar para mudar as configurações.")
            return
        d = ctk.CTkToplevel(self)
        d.title("Configurações")
        set_icon(d)
        d.geometry("520x430")
        d.resizable(False, False)
        d.configure(fg_color=BG)
        d.transient(self)
        ctk.CTkLabel(d, text="Configurações de transferência", font=(UI, 17, "bold"), text_color=TEXT
                     ).pack(anchor="w", padx=22, pady=(20, 12))

        ctk.CTkLabel(d, text="Arquivos ao mesmo tempo (envio e download)", font=(UI, 13, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=22)
        ctk.CTkLabel(d, text="Mais arquivos juntos usam melhor a internet quando há muitos arquivos.\n"
                             "Em HD comum, acima de 8 costuma piorar.", font=(UI, 11), text_color=MUTED,
                     justify="left").pack(anchor="w", padx=22)
        v_tr = tk.StringVar(value=str(self.cfg("transfers")))
        ctk.CTkOptionMenu(d, values=["1", "2", "3", "4", "6", "8", "12", "16"], variable=v_tr, width=100,
                          fg_color=CARD2, button_color=ACCENT, button_hover_color=ACCENT_H,
                          dropdown_fg_color=CARD2).pack(anchor="w", padx=22, pady=(6, 16))

        ctk.CTkLabel(d, text="Limite de velocidade (MB/s)", font=(UI, 13, "bold"), text_color=TEXT
                     ).pack(anchor="w", padx=22)
        ctk.CTkLabel(d, text="Deixe 0 para usar o máximo da internet (padrão). Use um limite se a internet\n"
                             "da casa ou do escritório ficar lenta durante as transferências.",
                     font=(UI, 11), text_color=MUTED, justify="left").pack(anchor="w", padx=22)
        row = ctk.CTkFrame(d, fg_color="transparent")
        row.pack(anchor="w", padx=22, pady=(6, 0))
        v_up = tk.StringVar(value=str(self.cfg("bw_up")))
        v_dn = tk.StringVar(value=str(self.cfg("bw_down")))
        for label, var in (("Envio", v_up), ("Download", v_dn)):
            ctk.CTkLabel(row, text=label, font=(UI, 12), text_color=TEXT).pack(side="left")
            ctk.CTkEntry(row, textvariable=var, width=70, height=32, fg_color=CARD, border_color=CARD2,
                         corner_radius=8).pack(side="left", padx=(6, 22))
        ctk.CTkLabel(d, text="1 MB/s ≈ 8 Mbps (a medida das operadoras de internet).", font=(UI, 11),
                     text_color=MUTED).pack(anchor="w", padx=22, pady=(4, 0))

        def save():
            try:
                up, dn = int(float(v_up.get() or 0)), int(float(v_dn.get() or 0))
                if up < 0 or dn < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Configurações", "Use números inteiros (0 = sem limite).", parent=d)
                return
            self.settings.update({"transfers": int(v_tr.get()), "bw_up": up, "bw_down": dn})
            save_settings(self.settings)
            self.say(f"Configurações: {v_tr.get()} arquivos ao mesmo tempo; limite de envio "
                     f"{up or 'nenhum'}{' MB/s' if up else ''}, de download {dn or 'nenhum'}{' MB/s' if dn else ''}.")
            d.destroy()

        bot = ctk.CTkFrame(d, fg_color="transparent")
        bot.pack(fill="x", padx=22, pady=20, side="bottom")
        btn(bot, "Salvar", save, "primary", width=110).pack(side="right")
        btn(bot, "Cancelar", d.destroy, width=100).pack(side="right", padx=8)
        btn(bot, "Restaurar padrão", lambda: (v_tr.set(str(DEFAULTS["transfers"])), v_up.set("0"), v_dn.set("0")),
            width=130).pack(side="left")
        d.after(200, lambda: (d.lift(), d.focus_force(), d.grab_set()))

    def rclone_speed_flags(self):
        """Opcoes de desempenho comuns a envio e download."""
        tr = self.cfg("transfers")
        flags = ["--transfers", str(tr), "--checkers", str(max(8, tr * 2)), "--buffer-size", "32M"]
        up, dn = self.cfg("bw_up"), self.cfg("bw_down")
        if up or dn:
            flags += ["--bwlimit", f"{f'{up}M' if up else 'off'}:{f'{dn}M' if dn else 'off'}"]
        if self.settings.get("client_id"):  # com chave propria o limite de consultas e so seu: pode ir mais rapido
            flags += ["--drive-pacer-min-sleep", "10ms", "--drive-pacer-burst", "200"]
        return flags

    def update_key_button(self):
        has = bool(self.settings.get("client_id") and self.settings.get("client_secret"))
        self.btn_key.configure(text="Chave Google ✓" if has else "Chave Google ⚠")

    def key_dialog(self):
        if self.busy():
            return
        d = ctk.CTkToplevel(self)
        d.title("Chave própria do Google")
        set_icon(d)
        d.geometry("620x380")
        d.configure(fg_color=BG)
        d.transient(self)
        ctk.CTkLabel(
            d, justify="left", anchor="w", text_color=TEXT, font=(UI, 12), wraplength=580,
            text="Sem chave própria, o programa usa o acesso compartilhado do rclone, que é dividido com "
                 "usuários do mundo todo: fica lento, falha às vezes e será desativado pelo Google.\n\n"
                 "Com a sua chave (gratuita, criada uma vez no Google Cloud) isso acaba. Cole abaixo o "
                 "\"ID do cliente\" e a \"Chave secreta do cliente\".\n\n"
                 "Depois de salvar, remova e adicione de novo cada conta para ela passar a usar a chave."
        ).pack(fill="x", padx=18, pady=(16, 8))
        v_id = tk.StringVar(value=self.settings.get("client_id", ""))
        v_sec = tk.StringVar(value=self.settings.get("client_secret", ""))
        for label, var, show in (("ID do cliente", v_id, ""), ("Chave secreta do cliente", v_sec, "•")):
            ctk.CTkLabel(d, text=label, text_color=MUTED, font=(UI, 12, "bold")
                         ).pack(anchor="w", padx=18)
            ctk.CTkEntry(d, textvariable=var, show=show, height=34, fg_color=CARD, border_color=CARD2,
                         corner_radius=8).pack(fill="x", padx=18, pady=(0, 8))

        def save():
            cid, sec = v_id.get().strip(), v_sec.get().strip()
            if bool(cid) != bool(sec):
                messagebox.showerror("Chave", "Preencha os dois campos (ou deixe os dois vazios).", parent=d)
                return
            self.settings["client_id"], self.settings["client_secret"] = cid, sec
            save_settings(self.settings)
            self.update_key_button()
            d.destroy()
            if cid:
                messagebox.showinfo("Chave salva", "Chave salva.\n\nAgora remova e adicione de novo cada conta "
                                                   "para ela passar a usar a chave.")

        bot = ctk.CTkFrame(d, fg_color="transparent")
        bot.pack(fill="x", padx=18, pady=10)
        btn(bot, "Salvar", save, "primary", width=110).pack(side="right")
        btn(bot, "Cancelar", d.destroy, width=100).pack(side="right", padx=8)
        d.after(200, lambda: (d.lift(), d.focus_force(), d.grab_set()))

    def build_tabs(self):
        self.tabs = ctk.CTkTabview(
            self, fg_color=CARD, corner_radius=12, height=300,
            segmented_button_fg_color=CARD2, segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT_H,
            segmented_button_unselected_color=CARD2)
        self.tabs.pack(fill="x", padx=14, pady=6)
        up = self.tabs.add("⬆   Enviar para o Drive")
        down = self.tabs.add("⬇   Baixar do Drive")
        try:
            self.tabs._segmented_button.configure(font=(UI, 14, "bold"), height=36)
        except Exception:
            pass

        # ---------- ENVIAR
        ctk.CTkLabel(up, text="O que enviar", font=(UI, 13, "bold"), text_color=TEXT
                     ).grid(row=0, column=0, sticky="w", padx=6, pady=(2, 2))
        self.src_frame = ctk.CTkScrollableFrame(up, fg_color=BG, corner_radius=8, height=92)
        try:  # a barra de rolagem tem altura minima de 200; reduz para a lista ficar compacta
            self.src_frame._scrollbar.configure(height=0)
            self.src_frame._parent_canvas.configure(height=96)
        except Exception:
            pass
        self.src_frame.grid(row=1, column=0, sticky="ew", padx=6)
        side = ctk.CTkFrame(up, fg_color="transparent")
        side.grid(row=1, column=1, sticky="n", padx=(4, 6))
        btn(side, "📁  Adicionar pasta", self.add_folder, width=170).pack(pady=(0, 6))
        btn(side, "📄  Adicionar arquivos", self.add_files, width=170).pack(pady=(0, 6))
        btn(side, "Limpar lista", self.clear_items, width=170).pack()

        ctk.CTkLabel(up, text="Pasta de destino no Drive", font=(UI, 13, "bold"),
                     text_color=TEXT).grid(row=2, column=0, sticky="w", padx=6, pady=(10, 2))
        self.var_dest = tk.StringVar()
        self.cb_dest = ctk.CTkComboBox(
            up, variable=self.var_dest, values=[""], height=34, fg_color=BG,
            border_color=CARD2, button_color=CARD2, button_hover_color="#313948",
            dropdown_fg_color=CARD2, font=(UI, 13), corner_radius=8)
        self.cb_dest.grid(row=3, column=0, sticky="ew", padx=6)
        btn(up, "Procurar no Drive...", self.browse, width=170).grid(row=3, column=1, padx=(4, 6))
        ctk.CTkLabel(up, text="Ex.: Clientes/Flyworks   (vazio = raiz do Drive; se a pasta não existir, ela é criada)",
                     text_color=MUTED, font=(UI, 11)).grid(row=4, column=0, sticky="w", padx=6)
        opts = ctk.CTkFrame(up, fg_color="transparent")
        opts.grid(row=5, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 0))
        self.var_keep = tk.BooleanVar(value=self.settings.get("keep", True))
        ctk.CTkCheckBox(opts, text="Criar no destino uma pasta com o mesmo nome", variable=self.var_keep,
                        fg_color=ACCENT, hover_color=ACCENT_H, font=(UI, 12)).pack(side="left")
        self.var_shared = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(opts, text="Destino está em \"Compartilhados comigo\"", variable=self.var_shared,
                        fg_color=ACCENT, hover_color=ACCENT_H, font=(UI, 12)).pack(side="left", padx=18)
        self.btn_up = btn(up, "⬆   Enviar", self.start_upload, "primary", width=170, height=40,
                          font=(UI, 15, "bold"))
        self.btn_up.grid(row=5, column=1, padx=(4, 6), pady=(6, 0))
        up.grid_columnconfigure(0, weight=1)

        # ---------- BAIXAR
        ctk.CTkLabel(down, text="Link do Google Drive (pasta ou arquivo)", font=(UI, 13, "bold"),
                     text_color=TEXT).grid(row=0, column=0, sticky="w", padx=6, pady=(2, 2))
        self.var_link = tk.StringVar()
        self.ent_link = ctk.CTkEntry(down, textvariable=self.var_link, height=34, fg_color=BG,
                                     border_color=CARD2, font=(UI, 13), corner_radius=8,
                                     placeholder_text="https://drive.google.com/drive/folders/...")
        self.ent_link.grid(row=1, column=0, sticky="ew", padx=6)
        self.ent_link.bind("<Return>", lambda e: self.verify_link())
        lf = ctk.CTkFrame(down, fg_color="transparent")
        lf.grid(row=1, column=1, padx=(4, 6))
        btn(lf, "Colar", self.paste_link, width=70).pack(side="left", padx=(0, 6))
        btn(lf, "Verificar", self.verify_link, width=94).pack(side="left")

        self.lbl_meta = ctk.CTkLabel(down, text="Cole o link e clique em Verificar para ver o nome e o tamanho.",
                                     text_color=MUTED, font=(UI, 12), justify="left", anchor="w",
                                     fg_color=BG, corner_radius=8, height=62)
        self.lbl_meta.grid(row=2, column=0, columnspan=2, sticky="ew", padx=6, pady=(8, 0))

        ctk.CTkLabel(down, text="Salvar em (pasta do computador)", font=(UI, 13, "bold"),
                     text_color=TEXT).grid(row=3, column=0, sticky="w", padx=6, pady=(10, 2))
        self.var_dldir = tk.StringVar(value=self.settings.get("dl_dir", ""))
        ctk.CTkEntry(down, textvariable=self.var_dldir, height=34, fg_color=BG, border_color=CARD2,
                     font=(UI, 13), corner_radius=8).grid(row=4, column=0, sticky="ew", padx=6)
        btn(down, "Escolher pasta...", self.pick_dldir, width=170).grid(row=4, column=1, padx=(4, 6))
        self.var_dlkeep = tk.BooleanVar(value=self.settings.get("dl_keep", True))
        ctk.CTkCheckBox(down, text="Criar dentro dela uma pasta com o nome da pasta do Drive",
                        variable=self.var_dlkeep, fg_color=ACCENT, hover_color=ACCENT_H,
                        font=(UI, 12)).grid(row=5, column=0, sticky="w", padx=6, pady=(10, 0))
        self.btn_down = btn(down, "⬇   Baixar", self.start_download, "primary", width=170, height=40,
                            font=(UI, 15, "bold"))
        self.btn_down.grid(row=5, column=1, padx=(4, 6), pady=(10, 0))
        down.grid_columnconfigure(0, weight=1)

    def build_progress(self):
        f = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        f.pack(fill="both", expand=True, padx=14, pady=(6, 14))

        top = ctk.CTkFrame(f, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(12, 0))
        self.lbl_status = ctk.CTkLabel(top, text="Pronto.", font=(UI, 15, "bold"),
                                       text_color=TEXT, anchor="w")
        self.lbl_status.pack(side="left", fill="x", expand=True)
        self.btn_cancel = btn(top, "Cancelar", self.stop, "danger", width=110, state="disabled")
        self.btn_cancel.pack(side="right")
        self.btn_open = btn(top, "Abrir pasta", self.open_folder, width=110)

        bar = ctk.CTkFrame(f, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(8, 0))
        self.lbl_pct = ctk.CTkLabel(bar, text="0%", font=(UI, 22, "bold"), text_color=TEXT, width=74,
                                    anchor="e")
        self.lbl_pct.pack(side="right")
        self.pb = ctk.CTkProgressBar(bar, height=16, corner_radius=8, fg_color=BG, progress_color=ACCENT)
        self.pb.set(0)
        self.pb.pack(side="left", fill="x", expand=True, padx=(0, 10))

        cards = ctk.CTkFrame(f, fg_color="transparent")
        cards.pack(fill="x", padx=12, pady=(10, 4))
        self.cards = {}
        for i, (key, title) in enumerate([
                ("done", "TRANSFERIDO"), ("cur", "VELOCIDADE ATUAL"), ("avg", "VELOCIDADE MÉDIA"),
                ("elapsed", "TEMPO DECORRIDO"), ("eta", "TEMPO RESTANTE (TOTAL)")]):
            c = ctk.CTkFrame(cards, fg_color=BG, corner_radius=10)
            c.grid(row=0, column=i, sticky="ew", padx=4)
            cards.grid_columnconfigure(i, weight=1, uniform="c")
            ctk.CTkLabel(c, text=title, font=(UI, 10, "bold"), text_color=MUTED
                         ).pack(anchor="w", padx=12, pady=(8, 0))
            v = ctk.CTkLabel(c, text="--", font=(UI, 16, "bold"), text_color=TEXT)
            v.pack(anchor="w", padx=12, pady=(0, 8))
            self.cards[key] = v

        ctk.CTkLabel(f, text="Arquivos em andamento", font=(UI, 12, "bold"), text_color=MUTED
                     ).pack(anchor="w", padx=16, pady=(6, 0))
        self.rows_frame = ctk.CTkFrame(f, fg_color="transparent")
        self.rows_frame.pack(fill="x", padx=12)
        self.rows = []
        for i in range(MAX_ROWS):
            r = ctk.CTkFrame(self.rows_frame, fg_color=BG, corner_radius=8)
            name = ctk.CTkLabel(r, text="", font=(UI, 12), text_color=TEXT, anchor="w")
            name.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=(2, 0))
            info = ctk.CTkLabel(r, text="", font=(UI, 11), text_color=MUTED, anchor="e")
            info.grid(row=0, column=1, sticky="e", padx=(0, 4), pady=(2, 0))
            pct = ctk.CTkLabel(r, text="", font=(UI, 12, "bold"), text_color=TEXT, anchor="e", width=46)
            pct.grid(row=0, column=2, sticky="e", padx=(0, 12), pady=(2, 0))
            pb = ctk.CTkProgressBar(r, height=6, corner_radius=3, fg_color=CARD2, progress_color=GREEN)
            pb.set(0)
            pb.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 7))
            r.grid_columnconfigure(0, weight=1)
            self.rows.append((r, name, pct, pb, info))
        self.lbl_norows = ctk.CTkLabel(self.rows_frame, text="Nenhum arquivo em andamento.",
                                       text_color=MUTED, font=(UI, 12))
        self.lbl_norows.pack(anchor="w", padx=6, pady=4)
        self.lbl_more = ctk.CTkLabel(self.rows_frame, text="", text_color=MUTED, font=(UI, 11))

        self.log = ctk.CTkTextbox(f, height=80, fg_color=BG, text_color=MUTED, font=(MONO, 11),
                                  corner_radius=8, wrap="none", state="disabled")
        self.log.pack(fill="both", expand=True, padx=16, pady=(8, 14))

    # ------------------------------------------------------------ utilidades
    def say(self, text):
        self._logbuf.append(text)  # entra na tela de uma vez, no proximo ciclo (mais leve)

    def flush_log(self):
        if not self._logbuf:
            return
        lines, self._logbuf = self._logbuf, []
        self.log.configure(state="normal")
        self.log.insert("end", "\n".join(lines) + "\n")
        total = int(self.log.index("end-1c").split(".")[0])
        if total > LOG_MAX:
            self.log.delete("1.0", f"{total - LOG_MAX}.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set(self, widget, **kw):
        """Muda um texto/cor so se for diferente do atual (cada mudanca redesenha o elemento)."""
        key = id(widget)
        val = tuple(sorted(kw.items()))
        if self._last.get(key) != val:
            self._last[key] = val
            widget.configure(**kw)

    def _bar(self, pb, frac):
        frac = round(max(0.0, min(1.0, frac)), 3)
        key = ("pb", id(pb))
        if self._last.get(key) != frac:
            self._last[key] = frac
            pb.set(frac)

    def status(self, text, color=TEXT):
        self._set(self.lbl_status, text=text, text_color=color)

    def remote(self):
        return self.om_remote.get().strip()

    def remotes(self):
        return [v for v in self.om_remote.cget("values") if v]

    def persist(self):
        self.settings["last_remote"] = self.remote()
        self.settings["keep"] = self.var_keep.get()
        self.settings["dl_keep"] = self.var_dlkeep.get()
        self.settings["dl_dir"] = self.var_dldir.get().strip()
        save_settings(self.settings)

    def busy(self):
        return self.running or self.auth_proc is not None

    def set_controls(self, enabled):
        st = "normal" if enabled else "disabled"
        for w in (self.btn_up, self.btn_down, self.btn_add, self.btn_del, self.btn_rec, self.btn_key, self.om_remote):
            w.configure(state=st)

    # ---------------------------------------------------------------- contas
    def refresh_remotes(self, select=None):
        try:
            r = rclone(["listremotes", "--type", "drive"], timeout=30)
            names = [l.strip().rstrip(":") for l in r.stdout.splitlines() if l.strip()]
        except Exception:
            names = []
        self.om_remote.configure(values=names or [""])
        self.om_remote.set(select if select in names else (names[0] if names else ""))
        self.on_remote()

    def on_remote(self):
        name = self.remote()
        hist = self.settings.get("dest_history", {}).get(name, [])
        self.cb_dest.configure(values=hist or [""])
        self.var_dest.set(hist[0] if hist else "")
        self.var_shared.set(bool(self.settings.get("shared", {}).get(name, False)))
        if not name:
            self.lbl_email.configure(text="Nenhuma conta ainda: clique em \"+ Adicionar conta\".")
            return
        cache = self.settings.setdefault("emails", {})
        self.lbl_email.configure(text=cache.get(name, ""))
        if name in cache:
            return

        def work():
            try:
                email = account_email(name)
            except Exception:
                email = ""
            if email:
                self.q.put(("email", name, email))

        threading.Thread(target=work, daemon=True).start()

    def add_account(self):
        if self.busy():
            return
        dlg = ctk.CTkInputDialog(
            title="Adicionar conta",
            text="Dê um apelido para esta conta (sem espaços).\nEx.: pessoal, trabalho, cliente\n\n"
                 "Depois o navegador abre: escolha a conta Google e clique em Permitir.")
        name = (dlg.get_input() or "").strip()
        if not name:
            return
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            messagebox.showerror("Apelido inválido", "Use só letras, números, - e _ (sem espaços).")
            return
        if name in self.remotes():
            messagebox.showerror("Já existe", f"Já existe uma conta chamada \"{name}\".")
            return
        self.set_controls(False)
        self.btn_cancel.configure(state="normal", text="Cancelar login")
        self.status("Aguardando o login no navegador...")
        self.say(f"Adicionando conta \"{name}\": faça o login no navegador que abriu.")
        extra = []
        if self.settings.get("client_id") and self.settings.get("client_secret"):
            extra = ["client_id=" + self.settings["client_id"],
                     "client_secret=" + self.settings["client_secret"]]

        def work():
            err = ""
            try:
                self.auth_proc = subprocess.Popen(
                    [RCLONE, "--config", CONF, "config", "create", name, "drive",
                     "scope=drive", "config_is_local=true"] + extra,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                    text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
                _, err = self.auth_proc.communicate()
                code = self.auth_proc.returncode
            except Exception as e:
                code, err = 1, str(e)
            self.auth_proc = None
            ok = False
            if code == 0:
                try:
                    dump = json.loads(rclone(["config", "dump"], timeout=30).stdout)
                    ok = bool(dump.get(name, {}).get("token"))
                except Exception:
                    ok = False
            if not ok:
                try:
                    rclone(["config", "delete", name], timeout=30)
                except Exception:
                    pass
            self.q.put(("auth", name, ok, (err or "").strip()[-300:]))

        threading.Thread(target=work, daemon=True).start()

    def reconnect_account(self):
        """Refaz o login de uma conta que expirou, sem perder apelido nem historico."""
        name = self.remote()
        if not name or self.busy():
            return
        self.set_controls(False)
        self.btn_cancel.configure(state="normal", text="Cancelar login")
        self.status(f"Reconectando \"{name}\": faça o login no navegador que abriu...")
        self.say(f"Reconectando a conta \"{name}\": escolha a conta Google no navegador e clique em Permitir.")

        def work():
            try:
                self.auth_proc = subprocess.Popen(
                    [RCLONE, "--config", CONF, "config", "reconnect", name + ":", "--auto-confirm"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                    text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
                self.auth_proc.communicate()
            except Exception:
                pass
            self.auth_proc = None
            try:
                ok = rclone(["about", name + ":"], timeout=120).returncode == 0
            except Exception:
                ok = False
            self.q.put(("reauth", name, ok))

        threading.Thread(target=work, daemon=True).start()

    def del_account(self):
        name = self.remote()
        if not name or self.busy():
            return
        if not messagebox.askyesno(
                "Remover conta",
                f"Remover a conta \"{name}\" deste programa?\n\n"
                "Nada é apagado do Google Drive; só o login salvo aqui."):
            return
        rclone(["config", "delete", name], timeout=30)
        self.settings.get("emails", {}).pop(name, None)
        self.say(f"Conta \"{name}\" removida.")
        self.refresh_remotes()
        self.persist()

    # ---------------------------------------------------------------- origem
    def draw_items(self):
        for w in self.src_frame.winfo_children():
            w.destroy()
        if not self.items:
            ctk.CTkLabel(self.src_frame, text="Nada na lista. Adicione uma pasta ou arquivos ao lado.",
                         text_color=MUTED, font=(UI, 12)).pack(anchor="w", padx=6, pady=6)
            return
        for p in self.items:
            row = ctk.CTkFrame(self.src_frame, fg_color=CARD, corner_radius=6)
            row.pack(fill="x", pady=2)
            ctk.CTkButton(row, text="✕", width=26, height=24, fg_color="transparent", hover_color="#5a2a2e",
                          text_color=MUTED, command=lambda p=p: self.remove_item(p)).pack(side="right", padx=4)
            ctk.CTkLabel(row, text=("📁  " if os.path.isdir(p) else "📄  ") + p, anchor="w",
                         font=(UI, 12), text_color=TEXT).pack(side="left", fill="x", expand=True,
                                                                      padx=8, pady=2)

    def add_item(self, path):
        path = os.path.normpath(path)
        if path not in self.items:
            self.items.append(path)

    def add_folder(self):
        d = filedialog.askdirectory(title="Pasta para enviar",
                                    initialdir=self.settings.get("last_dir") or None)
        if d:
            self.settings["last_dir"] = os.path.dirname(d)
            self.add_item(d)
            self.draw_items()

    def add_files(self):
        fs = filedialog.askopenfilenames(title="Arquivos para enviar",
                                         initialdir=self.settings.get("last_dir") or None)
        for p in fs:
            self.add_item(p)
        if fs:
            self.settings["last_dir"] = os.path.dirname(fs[0])
            self.draw_items()

    def remove_item(self, path):
        if path in self.items:
            self.items.remove(path)
        self.draw_items()

    def clear_items(self):
        self.items = []
        self.draw_items()

    def browse(self):
        name = self.remote()
        if not name:
            messagebox.showinfo("Conta", "Adicione ou escolha uma conta primeiro.")
            return
        dlg = BrowseDialog(self, name, self.var_dest.get().replace("\\", "/"), self.var_shared.get())
        self.wait_window(dlg)
        if dlg.result is not None:
            self.var_dest.set(dlg.result)

    # ---------------------------------------------------------------- upload
    def start_upload(self):
        if self.busy():
            return
        name = self.remote()
        if not name:
            messagebox.showinfo("Conta", "Adicione ou escolha uma conta primeiro.")
            return
        if not self.items:
            messagebox.showinfo("Nada para enviar", "Adicione uma pasta ou arquivos na lista.")
            return
        missing = [p for p in self.items if not os.path.exists(p)]
        if missing:
            messagebox.showerror("Não encontrado", "Não achei:\n" + "\n".join(missing))
            return
        dest = self.var_dest.get().replace("\\", "/").strip().strip("/")
        shared = self.var_shared.get()
        if shared and not dest:
            messagebox.showinfo("Destino", "Em \"Compartilhados comigo\" é preciso escolher uma pasta de destino.")
            return
        email = self.settings.get("emails", {}).get(name, "")
        if not messagebox.askyesno(
                "Confirmar envio",
                f"Conta: {name}  {email}\n"
                f"Destino: /{dest}" + ("  (Compartilhados comigo)" if shared else "") + "\n"
                f"Itens: {len(self.items)}\n\nEnviar agora?"):
            return

        hist = self.settings.setdefault("dest_history", {}).setdefault(name, [])
        if dest in hist:
            hist.remove(dest)
        hist.insert(0, dest)
        del hist[12:]
        self.cb_dest.configure(values=hist)
        self.settings.setdefault("shared", {})[name] = shared
        self.persist()

        keep = self.var_keep.get()
        jobs = []
        for src in self.items:
            d = dest
            if os.path.isdir(src) and keep:
                base = os.path.basename(src.rstrip("\\/"))
                if base:
                    d = (d + "/" + base).strip("/")
            cmd = ["copy", src, f"{name}:{d}", "--drive-chunk-size", "128M"]
            if shared:
                cmd.append("--drive-shared-with-me")
            jobs.append({"label": os.path.basename(src.rstrip("\\/")) or src,
                         "log": f"{src}  ->  {name}:/{d}", "cmd": cmd, "src": src, "size": None})
        self.run_jobs(jobs, "Enviando", None)

    # -------------------------------------------------------------- download
    def paste_link(self):
        try:
            self.var_link.set(self.clipboard_get().strip())
        except Exception:
            return
        self.verify_link()

    def pick_dldir(self):
        d = filedialog.askdirectory(title="Onde salvar",
                                    initialdir=self.var_dldir.get().strip() or None)
        if d:
            self.var_dldir.set(os.path.normpath(d))
            self.show_meta()

    def verify_link(self):
        fid, rk = parse_link(self.var_link.get())
        if not fid:
            self.meta = None
            self.lbl_meta.configure(text="  Não reconheci esse link. Cole o link de uma pasta ou arquivo do Google Drive.",
                                    text_color=RED)
            self.pending_download = False
            return
        if not self.remotes():
            messagebox.showinfo("Conta", "Adicione uma conta primeiro.")
            return
        self.meta = None
        self.meta_token += 1
        tok = self.meta_token
        self.lbl_meta.configure(text="  Verificando o link...", text_color=MUTED)
        order = [self.remote()] + [r for r in self.remotes() if r != self.remote()]

        def work():
            last = ""
            expired = []
            for name in order:
                try:
                    m = file_meta(name, fid, rk)
                except RateLimited:
                    self.q.put(("meta_limit", tok))
                    return
                except LoginExpired:
                    expired.append(name)
                    continue
                except urllib.error.HTTPError as e:
                    last = f"sem acesso (erro {e.code})"
                    continue
                except Exception as e:
                    last = str(e)
                    continue
                info = {"id": m["id"], "rk": rk if m["id"] == fid else None, "name": m.get("name", ""),
                        "folder": m.get("mimeType") == FOLDER_MIME, "mime": m.get("mimeType", ""),
                        "size": int(m["size"]) if m.get("size") else None, "count": None,
                        "account": name, "link_id": fid}
                self.q.put(("meta", tok, info))
                if info["folder"]:
                    args = ["size", name + ":", "--drive-root-folder-id", info["id"], "--json", "--fast-list"]
                    if info["rk"]:
                        args += ["--drive-resource-key", info["rk"]]
                    try:
                        s = json.loads(rclone(args, timeout=900).stdout)
                        self.q.put(("size", tok, s.get("bytes"), s.get("count")))
                    except Exception:
                        self.q.put(("size", tok, None, None))
                return
            if expired:
                self.q.put(("meta_expired", tok, expired))
                return
            self.q.put(("meta_fail", tok, last))

        threading.Thread(target=work, daemon=True).start()

    def show_meta(self):
        m = self.meta
        if not m:
            return
        kind = "📁  Pasta" if m["folder"] else "📄  Arquivo"
        if m["size"] is None:
            calculating = m["folder"] and m["count"] is None and not m.get("size_failed")
            size = "calculando tamanho..." if calculating else "tamanho desconhecido"
        else:
            size = fmt_bytes(m["size"]) + (f" em {m['count']} arquivos" if m["count"] is not None else "")
        line2 = f"  Tamanho: {size}      Conta com acesso: {m['account']}"
        color = TEXT
        dl = self.var_dldir.get().strip()
        if dl:
            free = free_space(dl)
            if free is not None:
                line2 += f"      Livre no disco: {fmt_bytes(free)}"
                if m["size"] and m["size"] > free:
                    line2 += "   ⚠ NÃO CABE"
                    color = RED
        self.lbl_meta.configure(text=f"  {kind}:  {m['name']}\n{line2}", text_color=color)

    def start_download(self):
        if self.busy():
            return
        fid, _ = parse_link(self.var_link.get())
        if not fid:
            messagebox.showinfo("Link", "Cole o link de uma pasta ou arquivo do Google Drive.")
            return
        dl = self.var_dldir.get().strip()
        if not dl:
            messagebox.showinfo("Onde salvar", "Escolha a pasta do computador onde quer salvar.")
            return
        if not self.meta or self.meta["link_id"] != fid:
            self.pending_download = True
            self.verify_link()
            return
        self.pending_download = False
        m = self.meta
        dest = os.path.normpath(dl)
        if m["folder"] and self.var_dlkeep.get():
            dest = os.path.join(dest, safe_name(m["name"]))
        free = free_space(dest)
        if m["size"] and free is not None and m["size"] > free:
            if not messagebox.askyesno("Espaço insuficiente",
                                       f"O download tem {fmt_bytes(m['size'])} e o disco só tem "
                                       f"{fmt_bytes(free)} livres.\n\nBaixar mesmo assim?"):
                return
        size = fmt_bytes(m["size"]) if m["size"] else "tamanho ainda não calculado"
        if not messagebox.askyesno(
                "Confirmar download",
                f"{'Pasta' if m['folder'] else 'Arquivo'}: {m['name']}\nTamanho: {size}\n"
                f"Conta: {m['account']}\nSalvar em: {dest}\n\nBaixar agora?"):
            return
        old = find_partials(dest)
        if old:
            if messagebox.askyesno(
                    "Sobras de downloads anteriores",
                    f"Encontrei {len(old)} arquivo(s) incompleto(s) (.partial) de downloads interrompidos "
                    f"nesta pasta, somando {fmt_bytes(sum(s for _, s in old))}.\n\n"
                    "Eles não são reaproveitados e só ocupam espaço. Apagar antes de começar?"):
                n, freed = delete_files(old)
                self.say(f"Apagados {n} arquivo(s) .partial antigos ({fmt_bytes(freed)} liberados).")
        self.persist()
        name = m["account"]
        if m["folder"]:
            cmd = ["copy", name + ":", dest, "--drive-root-folder-id", m["id"], "--fast-list"]
        else:
            cmd = ["backend", "copyid", name + ":", m["id"], dest + os.sep]
        if m["rk"]:
            cmd += ["--drive-resource-key", m["rk"]]
        # Um fluxo por arquivo: a integridade (md5) e conferida enquanto grava, e cada arquivo
        # perde o ".partial" assim que termina. Com varios fluxos o rclone precisa reler o
        # arquivo inteiro no fim, o que levou minutos nos testes (e horas em arquivos grandes).
        # A velocidade vem de baixar ate 4 arquivos ao mesmo tempo.
        cmd += ["--multi-thread-streams", "0"]
        jobs = [{"label": m["name"], "log": f"{m['name']}  ->  {dest}", "cmd": cmd, "src": None,
                 "size": m["size"]}]
        self.run_jobs(jobs, "Baixando", dest)

    def open_folder(self):
        if self.open_path and os.path.isdir(self.open_path):
            if IS_WIN:
                os.startfile(self.open_path)
            else:
                subprocess.Popen(["open" if IS_MAC else "xdg-open", self.open_path])

    # ----------------------------------------------------------- execucao
    def run_jobs(self, jobs, verb, open_path):
        self.running, self.cancel = True, False
        self.verb = verb
        self.open_path = open_path
        self.btn_open.pack_forget()
        self.set_controls(False)
        self.btn_cancel.configure(state="normal", text="Cancelar")
        self.pb.configure(progress_color=ACCENT)
        self._bar(self.pb, 0)
        self._set(self.lbl_pct, text="0%")
        for v in self.cards.values():
            self._set(v, text="--")
        self.status(f"{verb}: preparando...")
        threading.Thread(target=self.worker, args=(jobs,), daemon=True).start()

    def worker(self, jobs):
        failed = []
        for j in jobs:  # tamanho dos itens locais, para estimar o tempo total da fila
            if j["size"] is None and j["src"]:
                try:
                    j["size"] = local_size(j["src"])
                except Exception:
                    j["size"] = 0
        for i, j in enumerate(jobs):
            if self.cancel:
                break
            rest = sum((x["size"] or 0) for x in jobs[i + 1:])
            self.q.put(("item", i + 1, len(jobs), j["label"], rest))
            self.q.put(("log", f"[{i + 1}/{len(jobs)}] {j['log']}"))
            cmd = [RCLONE, "--config", CONF] + j["cmd"] + self.rclone_speed_flags() + [
                "--use-json-log", "--stats", "1s", "-v"]
            try:
                self.proc = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                    creationflags=NOWIN)
                for line in self.proc.stderr:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        self.q.put(("log", line))
                        continue
                    msg = str(d.get("msg", ""))
                    if "stats" in d:
                        self.q.put(("stats", d["stats"]))
                    elif d.get("level") in ("error", "critical"):
                        obj = str(d.get("object", ""))
                        self.q.put(("log", "ERRO: " + (obj + ": " if obj else "") + msg))
                    elif msg.startswith("Copied") or msg.startswith("Multi-thread Copied"):
                        self.q.put(("log", "  ok  " + str(d.get("object", ""))))
                code = self.proc.wait()
            except Exception as e:
                code = 1
                self.q.put(("log", f"ERRO: {e}"))
            self.proc = None
            if code != 0 and not self.cancel:
                failed.append(j["label"])
        self.q.put(("done", failed, self.cancel))

    def stop(self):
        if self.auth_proc:
            try:
                self.auth_proc.kill()
            except Exception:
                pass
            return
        if not self.running:
            return
        if messagebox.askyesno("Cancelar", "Parar agora?\n\n"
                               "O que já foi transferido fica salvo; repetindo depois ele continua de onde parou."):
            self.cancel = True
            p = self.proc
            if p:
                try:
                    p.terminate()
                except Exception:
                    pass

    def show_rows(self, transferring):
        tr = transferring or []
        if tr:
            self.lbl_norows.pack_forget()
        elif not self.lbl_norows.winfo_ismapped():
            self.lbl_norows.pack(anchor="w", padx=6, pady=4)
        for i, (frame, name, pct, pb, info) in enumerate(self.rows):
            if i >= len(tr):
                if frame.winfo_ismapped():
                    frame.pack_forget()
                continue
            t = tr[i]
            size, done = t.get("size") or 0, t.get("bytes") or 0
            p = t.get("percentage")
            if p is None:
                p = 100.0 * done / size if size else 0
            nm = str(t.get("name", ""))
            self._set(name, text=nm if len(nm) <= 46 else "..." + nm[-43:])
            self._set(pct, text=f"{p:.0f}%")
            self._bar(pb, p / 100.0)
            if size and done >= size:
                self._set(info, text=f"{fmt_bytes(size)}   ·   recebido, conferindo integridade antes de finalizar...")
            else:
                self._set(info, text=(
                    f"{fmt_bytes(done)} de {fmt_bytes(size)}   ·   {fmt_speed(t.get('speed'))}"
                    f"   ·   falta {fmt_time(t.get('eta'))}"))
            if not frame.winfo_ismapped():
                frame.pack(fill="x", pady=1, before=self.lbl_more if self.lbl_more.winfo_ismapped() else None)
        extra = len(tr) - len(self.rows)
        if extra > 0:
            self._set(self.lbl_more, text=f"+ {extra} arquivo(s) em andamento ao mesmo tempo")
            if not self.lbl_more.winfo_ismapped():
                self.lbl_more.pack(anchor="w", padx=6)
        elif self.lbl_more.winfo_ismapped():
            self.lbl_more.pack_forget()

    # ------------------------------------------------------- fila de eventos
    def poll(self):
        last_stats = None
        try:
            while True:
                ev = self.q.get_nowait()
                kind = ev[0]
                if kind == "stats":  # so a mais recente importa: evita redesenhar varias vezes por ciclo
                    last_stats = ev[1]
                    continue
                if last_stats is not None and kind in ("item", "done"):
                    self.on_stats(last_stats)
                    last_stats = None
                if kind == "log":
                    self.say(ev[1])
                elif kind == "item":
                    _, i, n, label, rest = ev
                    self.rest_bytes = rest
                    self.job_info = (f"item {i} de {n}  ·  " if n > 1 else "") + label
                    self._bar(self.pb, 0)
                    self._set(self.lbl_pct, text="0%")
                    self.status(f"{self.verb}:  {self.job_info}  (conferindo o que falta...)")
                elif kind == "stats":
                    self.on_stats(ev[1])
                elif kind == "email":
                    self.settings.setdefault("emails", {})[ev[1]] = ev[2]
                    save_settings(self.settings)
                    if self.remote() == ev[1]:
                        self.lbl_email.configure(text=ev[2])
                elif kind == "meta":
                    if ev[1] == self.meta_token:
                        self.meta = ev[2]
                        self.show_meta()
                        if self.pending_download:
                            self.after(50, self.start_download)
                elif kind == "size":
                    if ev[1] == self.meta_token and self.meta:
                        if ev[2] is not None:
                            self.meta["size"], self.meta["count"] = ev[2], ev[3]
                        else:
                            self.meta["size_failed"] = True
                        self.show_meta()
                elif kind == "meta_limit":
                    if ev[1] == self.meta_token:
                        self.pending_download = False
                        self.lbl_meta.configure(
                            text="  O Google está limitando as consultas agora. Tente de novo em 1 minuto.\n"
                                 "  Para acabar com isso, cadastre sua chave própria no botão \"Chave Google\".",
                            text_color=RED)
                elif kind == "reauth":
                    _, name, ok = ev
                    self.set_controls(True)
                    self.btn_cancel.configure(state="disabled", text="Cancelar")
                    if ok:
                        self.status(f"Conta \"{name}\" reconectada.", GREEN)
                        self.say(f"Conta \"{name}\" reconectada.")
                    else:
                        self.status(f"Não foi possível reconectar \"{name}\".", RED)
                        self.say(f"Reconexão de \"{name}\" não concluída. Tente de novo ou remova e adicione a conta.")
                elif kind == "meta_expired":
                    if ev[1] == self.meta_token:
                        self.pending_download = False
                        contas = ", ".join(ev[2])
                        self.lbl_meta.configure(
                            text=f"  O login da(s) conta(s) {contas} expirou: o Google pede para entrar de novo.\n"
                                 "  Escolha a conta no topo e clique em \"Reconectar\". Depois clique em Verificar.",
                            text_color=RED)
                        self.say(f"Login expirado: {contas}. Use o botão Reconectar.")
                elif kind == "meta_fail":
                    if ev[1] == self.meta_token:
                        self.pending_download = False
                        self.lbl_meta.configure(
                            text="  Nenhuma das contas cadastradas tem acesso a esse link.\n"
                                 f"  Adicione a conta que tem acesso, ou peça o compartilhamento.  ({ev[2]})",
                            text_color=RED)
                elif kind == "auth":
                    _, name, ok, err = ev
                    self.set_controls(True)
                    self.btn_cancel.configure(state="disabled", text="Cancelar")
                    if ok:
                        self.say(f"Conta \"{name}\" adicionada.")
                        self.status("Conta adicionada.", GREEN)
                        self.refresh_remotes(name)
                        self.persist()
                    else:
                        self.say(f"Login da conta \"{name}\" não foi concluído. {err}")
                        self.status("Login não concluído.", RED)
                        self.refresh_remotes(self.remote())
                elif kind == "done":
                    self.on_done(ev[1], ev[2])
        except queue.Empty:
            pass
        if last_stats is not None:
            self.on_stats(last_stats)
        self.flush_log()
        self.after(200, self.poll)

    def on_stats(self, s):
        total, done = s.get("totalBytes") or 0, s.get("bytes") or 0
        elapsed = s.get("elapsedTime") or 0
        frac = done / total if total else 0
        self._bar(self.pb, frac)
        self._set(self.lbl_pct, text=f"{frac * 100:.0f}%")
        avg = done / elapsed if elapsed > 1 and done else 0
        eta = s.get("eta")
        rest = getattr(self, "rest_bytes", 0)
        if eta is not None and rest and avg:
            eta = eta + rest / avg
        elif rest and eta is not None and not avg:
            eta = None
        self._set(self.cards["done"], text=f"{fmt_bytes(done)} / {fmt_bytes(total)}")
        # o "speed" geral do rclone e uma media desde o inicio; a velocidade de agora e a
        # soma da velocidade atual de cada arquivo em andamento (a mesma das linhas abaixo)
        tr = s.get("transferring") or []
        cur = sum((t.get("speed") or 0) for t in tr) if tr else 0
        self._set(self.cards["cur"], text=fmt_speed(cur))
        self._set(self.cards["avg"], text=fmt_speed(avg))
        self._set(self.cards["elapsed"], text=fmt_time(elapsed))
        self._set(self.cards["eta"], text=fmt_time(eta))
        files = f"{s.get('transfers', 0)} de {s.get('totalTransfers', 0)} arquivos"
        extra = "conferindo..." if s.get("checking") and not s.get("transferring") else files
        self.status(f"{self.verb}:  {self.job_info}   ({extra})")
        self.show_rows(s.get("transferring"))

    def on_done(self, failed, cancelled):
        self.running = False
        self.set_controls(True)
        self.btn_cancel.configure(state="disabled")
        self.show_rows([])
        self._set(self.cards["cur"], text="--")
        self._set(self.cards["eta"], text="--")
        if cancelled:
            self.status("Cancelado.", RED)
            self.say("Cancelado.")
        elif failed:
            self.pb.configure(progress_color=RED)
            self.status("Terminou COM ERROS: veja o registro abaixo.", RED)
            self.say("Terminou com erros em: " + "; ".join(failed))
            messagebox.showwarning("Terminou com erros",
                                   "Alguns itens não foram transferidos por completo:\n" + "\n".join(failed)
                                   + "\n\nRepita a operação para continuar de onde parou.")
        else:
            self.pb.configure(progress_color=GREEN)
            self._bar(self.pb, 1)
            self._set(self.lbl_pct, text="100%")
            self.status("Concluído: tudo transferido e conferido.", GREEN)
            self.say("Concluído.")
            self.bell()
        if self.open_path and not cancelled:
            self.btn_open.pack(side="right", padx=8)
        if self.open_path and (cancelled or failed):
            self.offer_partial_cleanup(self.open_path)

    def offer_partial_cleanup(self, dest):
        """Download interrompido: oferece apagar os .partial que o rclone deixou."""
        left = find_partials(dest)
        if not left:
            return
        total = sum(s for _, s in left)
        if messagebox.askyesno(
                "Arquivos incompletos",
                f"O download foi interrompido e ficaram {len(left)} arquivo(s) incompleto(s) (.partial), "
                f"ocupando {fmt_bytes(total)}.\n\nEles não são reaproveitados: baixando de novo, o arquivo "
                "começa do zero. Apagar agora?\n\n(Os arquivos que já terminaram não são afetados.)"):
            n, freed = delete_files(left)
            self.say(f"Apagados {n} arquivo(s) .partial ({fmt_bytes(freed)} liberados).")
        else:
            self.say(f"Mantidos {len(left)} arquivo(s) .partial em {dest}.")

    def on_close(self):
        if self.running:
            if not messagebox.askyesno("Sair", "Há uma transferência em andamento. Parar e sair?"):
                return
            self.cancel = True
            p = self.proc
            if p:
                try:
                    p.terminate()
                    p.wait(timeout=10)
                except Exception:
                    pass
            if self.open_path:
                self.offer_partial_cleanup(self.open_path)
        if self.auth_proc:
            try:
                self.auth_proc.kill()
            except Exception:
                pass
        self.persist()
        self.destroy()


if __name__ == "__main__":
    try:  # faz a barra de tarefas mostrar o icone do programa, e nao o do Python
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Rodrigo.DriveEnviarBaixar")
    except Exception:
        pass
    ctk.set_appearance_mode("dark")
    app = App()
    app.draw_items()
    app.mainloop()
