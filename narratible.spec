# -*- mode: python ; coding: utf-8 -*-
# narratible PyInstaller spec — GPU build only.
# All ML engines (transformers, kokoro, f5-tts, bitsandbytes) are expected
# to be installed in the build environment. Build will fail if they are absent.

import importlib.util
from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

datas = [('frontend/dist', 'frontend_dist')]
binaries = []
hiddenimports = []

# transformers lazy-loads many submodules dynamically; collect_all bundles them.
# copy_metadata ensures importlib.metadata lookups inside the frozen app succeed
# instead of raising StopIteration (fixed by rthook_metadata_fix.py at runtime).
_d, _b, _h = collect_all('transformers')
datas += _d
binaries += _b
hiddenimports += _h
for _pkg in [
    'transformers', 'torch', 'torchvision', 'torchaudio', 'torchcodec',
    'huggingface_hub', 'tokenizers', 'safetensors', 'accelerate',
    'sentencepiece', 'protobuf', 'Pillow', 'numpy',
]:
    try:
        datas += copy_metadata(_pkg)
    except Exception:
        pass

# Kokoro dynamically discovers its voice data and model helpers at runtime.
_d, _b, _h = collect_all('kokoro')
datas += _d
binaries += _b
hiddenimports += _h

# language_tags is a transitive Kokoro dependency that ships JSON data files.
# collect_all('kokoro') does not recursively collect dependency data, so we
# must add it explicitly — otherwise _internal/language_tags/data/json/ is missing.
_d, _b, _h = collect_all('language_tags')
datas += _d
binaries += _b
hiddenimports += _h

# espeakng_loader ships the espeak-ng-data directory used by Kokoro's phonemizer.
_d, _b, _h = collect_all('espeakng_loader')
datas += _d
binaries += _b
hiddenimports += _h

# misaki ships pronunciation dictionary JSON/text files (us_gold, gb_gold, etc.)
_d, _b, _h = collect_all('misaki')
datas += _d
binaries += _b
hiddenimports += _h

# spaCy is used by misaki's G2P for tokenisation/POS tagging.
# en_core_web_sm is the spaCy model misaki loads; collect its data files and
# metadata so spacy.util.is_package('en_core_web_sm') returns True in the
# frozen app and the model loads without triggering a network download.
_d, _b, _h = collect_all('spacy')
datas += _d
binaries += _b
hiddenimports += _h

_d, _b, _h = collect_all('en_core_web_sm')
datas += _d
binaries += _b
hiddenimports += _h
try:
    datas += copy_metadata('en_core_web_sm')
except Exception:
    pass

# phonemizer ships festival/segments data files used for text-to-phoneme conversion.
_d, _b, _h = collect_all('phonemizer')
datas += _d
binaries += _b
hiddenimports += _h

# F5-TTS uses dynamic imports internally.
_d, _b, _h = collect_all('f5_tts')
datas += _d
binaries += _b
hiddenimports += _h

# bitsandbytes loads platform-specific shared libraries via ctypes.
_d, _b, _h = collect_all('bitsandbytes')
datas += _d
binaries += _b
hiddenimports += _h

# TorchScript (torch.jit.script) calls inspect.getsource() at model-load time,
# which requires real .py files on disk — PyInstaller normally discards them.
# collect_data_files with include_py_files=True copies the source alongside the
# compiled bytecode in _internal/ so inspect can find them by path.
for _ts_pkg in ['vocos', 'f5_tts']:
    try:
        datas += collect_data_files(_ts_pkg, include_py_files=True)
    except Exception:
        pass

a = Analysis(
    ['desktop_app.py'],
    pathex=['backend'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['packaging/rthook_metadata_fix.py'],
    excludes=[],
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
    console=True,
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
