@echo off
echo Installing dependencies...
pip install -r requirements.txt
pip install pyinstaller

echo Building Windows executable...
pyinstaller build_exe.spec

echo Done!
echo Executable created in: dist\GamepadTest\GamepadTest.exe
pause
