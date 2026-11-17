#!/bin/bash
# Instalador do "Drive Enviar e Baixar" para macOS.
# Instala tudo na sua pasta de usuario; nao precisa de senha de administrador.
# Rodar de novo atualiza o programa e mantem as contas e a chave ja configuradas.

APP_NOME="Drive Enviar e Baixar"
DATA="$HOME/Library/Application Support/$APP_NOME"
cd "$(dirname "$0")" || exit 1

fim() {
  echo ""
  read -n 1 -s -r -p "Pressione qualquer tecla para fechar esta janela..."
  echo ""
  exit "$1"
}

echo ""
echo "=== Instalando: $APP_NOME ==="
echo ""

# 1. Python com interface grafica (Tk 8.6 ou mais novo).
#    O /usr/bin/python3 da Apple e ignorado: tem interface antiga e pode abrir um pedido de instalacao.
PY=""
for c in /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
         /usr/local/bin/python3 /opt/homebrew/bin/python3; do
  [ -x "$c" ] || continue
  if "$c" -c 'import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 9) and tkinter.TkVersion >= 8.6 else 1)' 2>/dev/null; then
    PY="$c"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Nao encontrei o Python necessario."
  echo ""
  echo "Vou abrir a pagina de download do Python:"
  echo "  1. Baixe o 'macOS 64-bit universal2 installer' da versao mais recente."
  echo "  2. Instale normalmente."
  echo "  3. Rode este instalador de novo."
  open "https://www.python.org/downloads/macos/"
  fim 1
fi
echo "[1/4] Python encontrado: $("$PY" --version 2>&1)"

mkdir -p "$DATA/libs" || { echo "Nao consegui criar a pasta $DATA"; fim 1; }

# 2. rclone (o motor que faz as transferencias)
if [ "$(uname -m)" = "arm64" ]; then RC="osx-arm64"; else RC="osx-amd64"; fi
echo "[2/4] Baixando o rclone ($RC)..."
TMP="$(mktemp -d)"
if ! curl -fL --progress-bar -o "$TMP/rclone.zip" "https://downloads.rclone.org/rclone-current-$RC.zip"; then
  echo "Falha ao baixar o rclone. Verifique a internet e tente de novo."
  rm -rf "$TMP"
  fim 1
fi
unzip -q -o "$TMP/rclone.zip" -d "$TMP" || { echo "Falha ao descompactar o rclone."; rm -rf "$TMP"; fim 1; }
cp "$TMP"/rclone-*/rclone "$DATA/rclone" || { echo "Falha ao copiar o rclone."; rm -rf "$TMP"; fim 1; }
chmod +x "$DATA/rclone"
xattr -d com.apple.quarantine "$DATA/rclone" 2>/dev/null
rm -rf "$TMP"
echo "      $("$DATA/rclone" version | head -1)"

# 3. Bibliotecas da interface
echo "[3/4] Instalando as bibliotecas da interface..."
if ! "$PY" -m pip install --upgrade --target "$DATA/libs" customtkinter certifi \
     --disable-pip-version-check -q 2>"$DATA/pip.log"; then
  echo "Falha ao instalar as bibliotecas. Detalhes em: $DATA/pip.log"
  fim 1
fi

# 4. Programa e app
echo "[4/4] Criando o app..."
cp "app/drive_uploader.pyw" "app/icone.png" "$DATA/" || { echo "Nao achei a pasta 'app' ao lado do instalador."; fim 1; }

DEST="/Applications"
if [ ! -w "$DEST" ]; then
  DEST="$HOME/Applications"
  mkdir -p "$DEST"
fi
APP="$DEST/$APP_NOME.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "app/icone.icns" "$APP/Contents/Resources/icone.icns"

cat > "$APP/Contents/MacOS/abrir" <<EOF
#!/bin/bash
DATA="\$HOME/Library/Application Support/$APP_NOME"
exec "$PY" "\$DATA/drive_uploader.pyw" >>"\$DATA/app.log" 2>&1
EOF
chmod +x "$APP/Contents/MacOS/abrir"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NOME</string>
  <key>CFBundleDisplayName</key><string>$APP_NOME</string>
  <key>CFBundleIdentifier</key><string>local.drive-enviar-baixar</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>abrir</string>
  <key>CFBundleIconFile</key><string>icone</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF
touch "$APP"

echo ""
echo "Pronto! O app foi instalado em:"
echo "  $APP"
echo ""
echo "Abrindo o app agora. Para deixar no Dock: com ele aberto, clique com o"
echo "botao direito no icone do Dock > Opcoes > Manter no Dock."
open "$APP"
fim 0
