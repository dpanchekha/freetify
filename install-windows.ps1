$ErrorActionPreference = 'Stop'
$appDir = $PSScriptRoot
Set-Location $appDir
$python = Get-Command py -ErrorAction SilentlyContinue
if ($python) { $pythonCommand = 'py'; $pythonArgs = @('-3') } else {
  $python = Get-Command python -ErrorAction SilentlyContinue
  if (-not $python) { Write-Host 'Python 3 is required. Install it from https://www.python.org/downloads/windows/ and run this installer again.' -ForegroundColor Red; exit 1 }
  $pythonCommand = 'python'; $pythonArgs = @()
}
if (-not (Test-Path '.venv\Scripts\python.exe')) { Write-Host 'Creating Freetify environment...'; & $pythonCommand @pythonArgs -m venv .venv }
$venvPython = Join-Path $appDir '.venv\Scripts\python.exe'
Write-Host 'Installing Freetify dependencies...'
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt
$shortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Freetify.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $appDir 'start-freetify.bat'
$shortcut.WorkingDirectory = $appDir
$shortcut.Description = 'Start Freetify CS2 demo analysis'
$shortcut.Save()
Write-Host "Freetify installed. Desktop shortcut created at: $shortcutPath" -ForegroundColor Green
Start-Process -FilePath (Join-Path $appDir 'start-freetify.bat') -WorkingDirectory $appDir
