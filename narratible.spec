# -*- mode: python ; coding: utf-8 -*-
# narratible PyInstaller spec - slim base application.
# CUDA PyTorch, local TTS engines, and the embedded LLM are installed into
# managed sidecar runtimes and must not be frozen into this distribution.

datas = [
    ('frontend/dist', 'frontend_dist'),
    ('backend/runtime_profiles', 'runtime_profiles'),
    ('backend/app/runtime_worker_scripts', 'runtime_workers'),
    ('build/runtime-tools', 'runtime-tools'),
    ('packaging/logo.ico', 'packaging'),
    # Resemble Enhance must use an isolated Python/Torch environment. Ship a
    # real source worker because an external interpreter cannot import modules
    # from PyInstaller's PYZ archive.
    ('backend/app/voice_enhancement.py', 'optional_runtime'),
    ('backend/requirements-voice-enhancement.txt', 'optional_runtime'),
]
binaries = []
hiddenimports = ['pystray._win32']

a = Analysis(
    ['desktop_app.py'],
    pathex=['backend'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['packaging/rthook_metadata_fix.py'],
    excludes=[
        'accelerate', 'bitsandbytes', 'chatterbox', 'en_core_web_sm',
        'f5_tts', 'kokoro', 'librosa', 'misaki', 'onnxruntime', 'perth',
        'phonemizer', 'qwen_tts', 's3tokenizer', 'spacy', 'torch',
        'torchaudio', 'torchcodec', 'torchvision', 'transformers', 'vocos',
        'tkinter', '_tkinter',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='narratible',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='packaging/logo.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='narratible',
)
