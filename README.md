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

## Preciso mesmo criar a chave do Google?

Não é obrigatório. Dá para usar o app só fazendo login nas contas, sem criar nada no Google Cloud. A diferença:

| | Só login (sem chave) | Com a sua chave do Google |
|---|---|---|
| **Configuração** | Nenhuma: instala, adiciona a conta e usa | ~10 min, uma vez só, no Google Cloud (passo a passo no LEIA-ME) |
| **Quem fornece o acesso** | O acesso compartilhado do rclone, dividido entre usuários do mundo todo | Um acesso só seu |
| **Velocidade e estabilidade** | Pode ficar lento ou recusar pedidos nos horários de pico. Nos nossos testes, listar pastas chegou a travar por minutos e a verificação de links foi recusada várias vezes ("O Google está limitando as consultas") | Rápido e estável: o limite de consultas é só seu |
| **Onde mais pesa** | Pastas com muitos arquivos pequenos e verificação de links. Arquivos grandes, depois que começam, sobem e descem bem | Sem diferença entre os casos |
| **Futuro** | O próprio rclone avisa que esse acesso compartilhado **está sendo desativado pelo Google em 2026**. Pode parar de funcionar a qualquer momento | Não depende do rclone |
| **Tela de login** | Normal, sem avisos | Mostra "O Google não verificou este app" (é o seu app; basta clicar em Avançado → Acessar) |
| **Validade do login** | Não expira | Não expira se você publicar o app; em modo Teste, expira a cada 7 dias |
| **Contas de empresa (Google Workspace)** | O administrador pode bloquear | O administrador pode bloquear |

**Resumo:** para experimentar ou para uso leve, o login sozinho resolve. Para trabalho do dia a dia, com pastas grandes ou muitos arquivos, vale criar a chave. E dá para começar sem e colocar a chave depois: é só colar no botão **Chave Google** e adicionar as contas de novo.

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
