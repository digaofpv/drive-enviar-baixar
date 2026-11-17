# Drive Enviar e Baixar

Envia pastas inteiras para o Google Drive e baixa pastas por link, direto no disco: **sem cache, sem compactar em zip** e com progresso, velocidade e tempo restante de cada arquivo. Funciona com várias contas Google. Para Windows e Mac.

Feito para quem trabalha com arquivos grandes (vídeo, bruto de câmera) e cansou do upload pelo navegador falhando, do app do Drive enchendo o disco de cache e de ter que zipar/deszipar pasta para baixar.

## Baixar e instalar

1. Baixe o **`Drive Enviar e Baixar.zip`** na página de [Releases](../../releases/latest).
2. Descompacte e abra o **`LEIA-ME.html`**: ele tem o passo a passo completo, inclusive como criar a sua chave gratuita do Google.
3. Rode o instalador do seu sistema:
   - Windows: `Instalar - Windows.bat`
   - Mac: `Instalar - Mac.command`

O instalador baixa o que falta (Python, se você deixar, o [rclone](https://rclone.org) e as bibliotecas da interface) e cria o atalho com ícone.

## O que ele faz

- **Enviar:** escolha pastas e arquivos, a conta e a pasta de destino no Drive. Se cair a conexão, é só enviar de novo: ele pula o que já subiu e confere tudo por checksum.
- **Baixar por link:** cole o link de uma pasta ou arquivo do Drive, escolha onde salvar. Ele descobre sozinho qual das suas contas tem acesso ao link e avisa se não cabe no disco.
- **Métricas:** porcentagem e tempo restante de cada arquivo e do total, velocidade atual e média, tempo decorrido.
- **Várias contas:** alterna entre contas pessoais e de trabalho num menu.

## Segurança

- Nenhuma chave ou login vem neste repositório nem no zip. Cada pessoa cria a sua própria chave do Google (o LEIA-ME explica como).
- Os logins ficam só no computador de quem usa: `%LOCALAPPDATA%\Drive Enviar e Baixar` (Windows) ou `~/Library/Application Support/Drive Enviar e Baixar` (Mac).
- Nunca compartilhe os arquivos `rclone.conf` e `uploader_settings.json`: eles dão acesso aos seus Drives.

## Para quem quer mexer no código

- `drive_uploader.pyw`: o programa (Python + [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter), usando o rclone por baixo).
- `pacote/`: instaladores e LEIA-ME de quem recebe o app.
- `python montar_pacote.py` gera o zip (precisa do Pillow: `pip install pillow`).

## Créditos e licença

As transferências são feitas pelo [rclone](https://rclone.org) (licença MIT), baixado do site oficial durante a instalação. Este projeto usa a licença MIT: veja [LICENSE](LICENSE).
