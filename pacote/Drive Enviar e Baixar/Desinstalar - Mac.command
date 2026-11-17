#!/bin/bash
# Remove o "Drive Enviar e Baixar" deste Mac. Nada e apagado do Google Drive.

APP_NOME="Drive Enviar e Baixar"
DATA="$HOME/Library/Application Support/$APP_NOME"

echo ""
echo "=== Desinstalar: $APP_NOME ==="
echo ""
echo "Isto remove o app, as contas logadas e a chave do Google salvas neste Mac."
echo "Nada e apagado do Google Drive."
echo ""
read -r -p "Digite s e pressione Enter para confirmar: " R
if [ "$R" != "s" ] && [ "$R" != "S" ]; then
  echo "Cancelado. Nada foi removido."
else
  rm -rf "/Applications/$APP_NOME.app" "$HOME/Applications/$APP_NOME.app" "$DATA"
  echo "Removido."
fi
echo ""
read -n 1 -s -r -p "Pressione qualquer tecla para fechar esta janela..."
echo ""
