$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$BuildDrive = Get-PSDrive -PSProvider FileSystem | Sort-Object Free -Descending | Select-Object -First 1
$BuildRoot = Join-Path $BuildDrive.Root 'WuwaComboAssistantBuild'
New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null
$env:TEMP = $BuildRoot
$env:TMP = $BuildRoot

python -m pip install --upgrade -r requirements-dev.txt
python -m pytest -q

$env:PYTHONPATH = Join-Path $ProjectRoot 'src'
python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name '鸣潮逐键教练' `
  --paths (Join-Path $ProjectRoot 'src') `
  --add-data "$(Join-Path $ProjectRoot 'src\wuwa_assistant\assets');wuwa_assistant/assets" `
  --workpath (Join-Path $BuildRoot 'work') `
  --specpath (Join-Path $BuildRoot 'spec') `
  --distpath (Join-Path $ProjectRoot 'dist') `
  --collect-all pystray `
  --collect-all mss `
  (Join-Path $ProjectRoot 'launcher.py')

Write-Host "构建完成：$ProjectRoot\dist\鸣潮逐键教练.exe"
