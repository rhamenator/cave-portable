$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'CAVE-Portable.exe'
if (-not (Test-Path -LiteralPath $source)) {
    throw 'Extract the complete CAVE Portable ZIP before running this installer.'
}
$destination = Join-Path $env:LOCALAPPDATA 'Programs\CAVE Portable'
New-Item -ItemType Directory -Path $destination -Force | Out-Null
$application = Join-Path $destination 'CAVE-Portable.exe'
Copy-Item -LiteralPath $source -Destination $application -Force
$menu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$shortcut = Join-Path $menu 'CAVE Portable.lnk'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($shortcut)
$link.TargetPath = $application
$link.WorkingDirectory = $destination
$link.Description = 'CAVE Portable weather viewer'
$link.IconLocation = "$application,0"
$link.Save()
Write-Host "Installed CAVE Portable for this user. Open it from the Start Menu."
