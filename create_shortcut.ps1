$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
$exe = Join-Path $root 'dist\GamepadTest\GamepadTest.exe'
$icon = Join-Path $root 'icon.ico'

if (-not (Test-Path $exe)) {
    throw "Executable not found: $exe  (once build_windows.bat / build_exe.spec calistir)"
}

$WshShell = New-Object -ComObject WScript.Shell

$targets = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Gamepad Haptics.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'Gamepad Haptics.lnk')
)

foreach ($path in $targets) {
    $shortcut = $WshShell.CreateShortcut($path)
    $shortcut.TargetPath = $exe
    $shortcut.WorkingDirectory = Split-Path $exe -Parent
    $shortcut.IconLocation = if (Test-Path $icon) { "$icon,0" } else { "$exe,0" }
    $shortcut.Description = 'Gamepad Haptics Tester'
    $shortcut.Save()
    Write-Host "Kisayol olusturuldu: $path"
}
