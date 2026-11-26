$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$([System.IO.Path]::Combine([System.Environment]::GetFolderPath('Desktop'), 'GamepadTest.lnk'))")
$Shortcut.TargetPath = [System.IO.Path]::Combine($PSScriptRoot, 'dist', 'GamepadTest', 'GamepadTest.exe')
$Shortcut.WorkingDirectory = [System.IO.Path]::Combine($PSScriptRoot, 'dist', 'GamepadTest')
$Shortcut.IconLocation = [System.IO.Path]::Combine($PSScriptRoot, 'icon.png')
$Shortcut.Description = 'Gamepad Haptics Tester'
$Shortcut.Save()
Write-Host "Shortcut created on Desktop: GamepadTest.lnk"
