# Instalador do "Drive Enviar e Baixar" para Windows.
# Instala na pasta do usuario; nao precisa de administrador.
# Rodar de novo atualiza o programa e mantem as contas e a chave ja configuradas.
param(
    [string]$Destino = (Join-Path $env:LOCALAPPDATA 'Drive Enviar e Baixar'),
    [string]$PastaAtalhos = '',   # so para testes: cria os atalhos nesta pasta
    [switch]$NaoAbrir
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$APP_NOME = 'Drive Enviar e Baixar'
$APP_ID = 'Rodrigo.DriveEnviarBaixar'
$PKG = Split-Path -Parent $MyInvocation.MyCommand.Path

function Falha($msg) { Write-Host ''; Write-Host "ERRO: $msg" -ForegroundColor Red; exit 1 }

Write-Host ''
Write-Host "=== Instalando: $APP_NOME ===" -ForegroundColor Cyan
Write-Host ''

# 1. Python com interface grafica
function Testar-Python($exe, $extra) {
    try {
        $out = & $exe @extra -c "import sys, tkinter; print(sys.executable) if sys.version_info >= (3, 9) and tkinter.TkVersion >= 8.6 else None" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out -and (Test-Path $out.Trim())) { return $out.Trim() }
    } catch {}
    return $null
}
function Achar-Python {
    $cands = @()
    if (Get-Command py -ErrorAction SilentlyContinue) { $cands += ,@('py', @('-3')) }
    if (Get-Command python -ErrorAction SilentlyContinue) { $cands += ,@('python', @()) }
    foreach ($base in @("$env:LOCALAPPDATA\Programs\Python", "$env:ProgramFiles")) {
        Get-ChildItem $base -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | ForEach-Object {
                $p = Join-Path $_.FullName 'python.exe'
                if (Test-Path $p) { $cands += ,@($p, @()) }
            }
    }
    foreach ($c in $cands) { $r = Testar-Python $c[0] $c[1]; if ($r) { return $r } }
    return $null
}

$PY = Achar-Python
if (-not $PY) {
    Write-Host 'Nao encontrei o Python necessario.' -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $r = Read-Host 'Instalar o Python automaticamente agora? (s/n)'
        if ($r -match '^[sS]') {
            winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
            $PY = Achar-Python
        }
    }
    if (-not $PY) {
        Write-Host ''
        Write-Host 'Vou abrir a pagina de download do Python:'
        Write-Host '  1. Baixe o instalador do Windows da versao mais recente.'
        Write-Host '  2. Na primeira tela, marque "Add python.exe to PATH" e instale.'
        Write-Host '  3. Rode este instalador de novo.'
        Start-Process 'https://www.python.org/downloads/windows/'
        exit 1
    }
}
$PYW = Join-Path (Split-Path $PY) 'pythonw.exe'
if (-not (Test-Path $PYW)) { $PYW = $PY }
Write-Host "[1/4] Python encontrado: $(& $PY --version 2>&1)"

New-Item -ItemType Directory -Force (Join-Path $Destino 'libs') | Out-Null

# 2. rclone (o motor que faz as transferencias)
$arq = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'windows-arm64' } else { 'windows-amd64' }
Write-Host "[2/4] Baixando o rclone ($arq, cerca de 30 MB)..."
$tmp = Join-Path $env:TEMP ('rclone_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force $tmp | Out-Null
try {
    Invoke-WebRequest -UseBasicParsing "https://downloads.rclone.org/rclone-current-$arq.zip" -OutFile "$tmp\rclone.zip"
    Expand-Archive "$tmp\rclone.zip" -DestinationPath $tmp -Force
    $exe = Get-ChildItem $tmp -Recurse -Filter 'rclone.exe' | Select-Object -First 1
    Copy-Item $exe.FullName (Join-Path $Destino 'rclone.exe') -Force
} catch {
    Falha "nao consegui baixar o rclone. Verifique a internet e tente de novo. ($($_.Exception.Message))"
} finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host "      $((& (Join-Path $Destino 'rclone.exe') version) | Select-Object -First 1)"

# 3. Bibliotecas da interface
Write-Host '[3/4] Instalando as bibliotecas da interface...'
$pipLog = Join-Path $Destino 'pip.log'
& $PY -m pip install --upgrade --target (Join-Path $Destino 'libs') customtkinter certifi qrcode --disable-pip-version-check -q 2> $pipLog
if ($LASTEXITCODE -ne 0) { Falha "nao consegui instalar as bibliotecas. Detalhes em: $pipLog" }

# 4. Programa e atalhos
Write-Host '[4/4] Criando os atalhos...'
foreach ($f in 'drive_uploader.pyw', 'icone.ico', 'icone.png') {
    $src = Join-Path $PKG $f
    if (-not (Test-Path $src)) { Falha "nao achei o arquivo $f na pasta 'app'." }
    Copy-Item $src $Destino -Force
}
Get-ChildItem $Destino -File | Unblock-File -ErrorAction SilentlyContinue

Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices; using System.Runtime.InteropServices.ComTypes;
public static class LnkAppId {
  [ComImport, Guid("00021401-0000-0000-C000-000000000046")] class CShellLink {}
  [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
  interface IPropertyStore { int GetCount(out uint c); int GetAt(uint i, out PKEY k); int GetValue(ref PKEY k, out PV v); int SetValue(ref PKEY k, ref PV v); int Commit(); }
  [StructLayout(LayoutKind.Sequential, Pack=4)] struct PKEY { public Guid fmtid; public uint pid; }
  [StructLayout(LayoutKind.Explicit, Size=24)] struct PV { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; }
  public static void Set(string path, string id) {
    object o = new CShellLink(); ((IPersistFile)o).Load(path, 2);
    PKEY k; k.fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"); k.pid = 5;
    PV v = new PV(); v.vt = 31; v.p = Marshal.StringToCoTaskMemUni(id);
    IPropertyStore s = (IPropertyStore)o; int hr = s.SetValue(ref k, ref v); if (hr != 0) Marshal.ThrowExceptionForHR(hr);
    hr = s.Commit(); if (hr != 0) Marshal.ThrowExceptionForHR(hr);
    ((IPersistFile)o).Save(path, true); Marshal.FreeCoTaskMem(v.p);
  }
}
'@ -ErrorAction SilentlyContinue

if ($PastaAtalhos) {
    $locais = @($PastaAtalhos)
} else {
    $locais = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
}
$ws = New-Object -ComObject WScript.Shell
foreach ($dir in $locais) {
    New-Item -ItemType Directory -Force $dir | Out-Null
    $lnk = Join-Path $dir "$APP_NOME.lnk"
    $l = $ws.CreateShortcut($lnk)
    $l.TargetPath = $PYW
    $l.Arguments = '"' + (Join-Path $Destino 'drive_uploader.pyw') + '"'
    $l.WorkingDirectory = $Destino
    $l.IconLocation = (Join-Path $Destino 'icone.ico') + ',0'
    $l.Description = 'Enviar e baixar pastas e arquivos do Google Drive'
    $l.Save()
    try { [LnkAppId]::Set($lnk, $APP_ID) } catch {}
}

Write-Host ''
Write-Host 'Pronto! Atalhos criados na Area de Trabalho e no Menu Iniciar.' -ForegroundColor Green
Write-Host "Programa instalado em: $Destino"
Write-Host 'Para fixar na barra de tarefas: Menu Iniciar > Drive Enviar e Baixar > botao direito > Fixar na barra de tarefas.'
if (-not $NaoAbrir) { Start-Process (Join-Path $locais[0] "$APP_NOME.lnk") }
exit 0
