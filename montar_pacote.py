# -*- coding: utf-8 -*-
"""Monta o pacote (Mac + Windows) a partir da versao atual do programa.

Uso:  python montar_pacote.py
Gera pacote/Drive Enviar e Baixar.zip, pronto para compartilhar.
Nunca copia logins ou chaves (rclone.conf / uploader_settings.json).
Precisa da biblioteca Pillow (pip install pillow).
"""
import os
import shutil
import stat
import sys
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "libs"))
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

PKG = os.path.join(BASE, "pacote", "Drive Enviar e Baixar")
APPDIR = os.path.join(PKG, "app")
ZIP = os.path.join(BASE, "pacote", "Drive Enviar e Baixar.zip")
PROIBIDOS = {"rclone.conf", "uploader_settings.json"}


def desenhar_icone(margem, S=1024):
    """Nuvem com setas de enviar/baixar. margem 24 = Windows; 100 = Mac (icones do macOS tem respiro)."""
    k = (S - 2 * margem) / (S - 48)
    o = margem - 24 * k

    def P(v):
        return o + v * k

    grad = Image.new("RGB", (S, S))
    gd = ImageDraw.Draw(grad)
    top, bot = (86, 160, 255), (24, 70, 210)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([margem, margem, S - margem, S - margem], radius=230 * k, fill=255)
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    icon.paste(grad, (0, 0), mask)

    def cloud(draw, dy=0, fill=255):
        draw.ellipse([P(230), P(380 + dy), P(530), P(680 + dy)], fill=fill)
        draw.ellipse([P(360), P(250 + dy), P(720), P(610 + dy)], fill=fill)
        draw.ellipse([P(560), P(400 + dy), P(810), P(650 + dy)], fill=fill)
        draw.rounded_rectangle([P(230), P(500 + dy), P(810), P(720 + dy)], radius=110 * k, fill=fill)

    sh = Image.new("L", (S, S), 0)
    cloud(ImageDraw.Draw(sh), dy=26, fill=120)
    sh = sh.filter(ImageFilter.GaussianBlur(26 * k))
    shadow = Image.new("RGBA", (S, S), (10, 30, 110, 255))
    shadow.putalpha(Image.composite(sh, Image.new("L", (S, S), 0), mask))
    icon = Image.alpha_composite(icon, shadow)
    cm = Image.new("L", (S, S), 0)
    cloud(ImageDraw.Draw(cm))
    white = Image.new("RGBA", (S, S), (255, 255, 255, 255))
    white.putalpha(cm)
    icon = Image.alpha_composite(icon, white)
    d = ImageDraw.Draw(icon)
    blue, green = (29, 78, 216, 255), (22, 163, 74, 255)
    x = 420
    d.polygon([(P(x), P(395)), (P(x - 88), P(500)), (P(x + 88), P(500))], fill=blue)
    d.rounded_rectangle([P(x - 32), P(485), P(x + 32), P(650)], radius=14 * k, fill=blue)
    x = 620
    d.rounded_rectangle([P(x - 32), P(420), P(x + 32), P(585)], radius=14 * k, fill=green)
    d.polygon([(P(x), P(675)), (P(x - 88), P(570)), (P(x + 88), P(570))], fill=green)
    return icon


def main():
    os.makedirs(APPDIR, exist_ok=True)
    shutil.copy(os.path.join(BASE, "drive_uploader.pyw"), APPDIR)
    desenhar_icone(24).save(os.path.join(APPDIR, "icone.ico"),
                            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    mac = desenhar_icone(100)
    mac.save(os.path.join(APPDIR, "icone.icns"), format="ICNS")
    mac.resize((512, 512), Image.LANCZOS).save(os.path.join(APPDIR, "icone.png"))

    for root, _, files in os.walk(PKG):
        for f in files:
            p = os.path.join(root, f)
            if f.endswith(".command"):  # Mac: quebra de linha LF
                data = open(p, "rb").read().replace(b"\r\n", b"\n")
            elif f.endswith((".bat", ".ps1")):  # Windows: CRLF; .ps1 com BOM
                data = open(p, "rb").read().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                if f.endswith(".ps1") and not data.startswith(b"\xef\xbb\xbf"):
                    data = b"\xef\xbb\xbf" + data
            else:
                continue
            open(p, "wb").write(data)

    if os.path.exists(ZIP):
        os.remove(ZIP)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(PKG):
            dirs.sort()
            rel_root = os.path.relpath(root, os.path.dirname(PKG)).replace("\\", "/")
            zi = zipfile.ZipInfo(rel_root + "/")
            zi.create_system = 3
            zi.external_attr = ((stat.S_IFDIR | 0o755) << 16) | 0x10
            z.writestr(zi, b"")
            for f in sorted(files):
                if f in PROIBIDOS:
                    raise SystemExit(f"ERRO: {f} nao pode ir no pacote")
                full = os.path.join(root, f)
                zi = zipfile.ZipInfo(rel_root + "/" + f)
                zi.create_system = 3  # Unix: o Mac respeita as permissoes
                mode = 0o755 if f.endswith(".command") else 0o644
                zi.external_attr = (stat.S_IFREG | mode) << 16
                zi.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(zi, open(full, "rb").read())
    print("pacote:", ZIP)


if __name__ == "__main__":
    main()
