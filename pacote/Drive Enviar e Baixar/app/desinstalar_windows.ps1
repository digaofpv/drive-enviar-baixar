# Remove o "Drive Enviar e Baixar" deste computador. Nada e apagado do Google Drive.
param(
    [string]$Destino = (Join-Path $env:LOCALAPPDATA 'Drive Enviar e Baixar'),
    [string]$PastaAtalhos = '',   # so para testes
    [switch]$Sim
)
$APP_NOME = 'Drive Enviar e Baixar'

Write-Host ''
Write-Host "=== Desinstalar: $APP_NOME ===" -ForegroundColor Cyan
Write-Host ''
Write-Host 'Isto remove o programa, as contas logadas e a chave do Google salvas neste computador.'
Write-Host 'Nada e apagado do Google Drive.'
Write-Host ''
if (-not $Sim) {
    $r = Read-Host 'Digite s e pressione Enter para confirmar'
    if ($r -notmatch '^[sS]$') { Write-Host 'Cancelado. Nada foi removido.'; exit 0 }
}

# fecha o programa e transferencias em andamento desta instalacao
Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^(pythonw?|rclone)\.exe$' -and $_.CommandLine -and $_.CommandLine -like "*$Destino*"
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 800

$locais = if ($PastaAtalhos) { @($PastaAtalhos) } else { @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) }
foreach ($dir in $locais) { Remove-Item (Join-Path $dir "$APP_NOME.lnk") -Force -ErrorAction SilentlyContinue }
Remove-Item $Destino -Recurse -Force -ErrorAction SilentlyContinue

if (Test-Path $Destino) { Write-Host "Nao consegui remover tudo em $Destino. Feche o programa e tente de novo." -ForegroundColor Yellow }
else { Write-Host 'Removido.' -ForegroundColor Green }
