# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['vibration_tester_simple.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('theme_colors.json', '.'),
        ('assets', 'assets'),
        ('icon.png', '.'),
    ],
    hiddenimports=['pygame', 'PyQt6', 'qfluentwidgets'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Bu uygulamanın ihtiyacı olmayan, hook zinciriyle gelen ağır paketler.
    # (PyInstaller ortamdaki her paketi toplamaya çalışıyordu; exe 1 GB+ oluyordu.)
    excludes=[
        'PyQt5',
        'torch', 'torchvision', 'torchaudio',
        'tensorflow', 'keras', 'transformers', 'onnxruntime',
        'cv2', 'av', 'pyarrow', 'pandas', 'numpy', 'scipy', 'sklearn',
        'matplotlib', 'nltk', 'spacy', 'soundfile',
        'pytest', 'IPython', 'ipykernel', 'jupyter', 'notebook', 'jedi',
        'boto3', 'botocore', 'google', 'uvicorn', 'websockets', 'yt_dlp',
        'sqlalchemy', 'openpyxl', 'lxml', 'cryptography',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GamepadTest',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.png',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GamepadTest',
)
