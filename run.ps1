$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = Join-Path $ProjectRoot 'src'
python -m wuwa_assistant

