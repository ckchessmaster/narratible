"""
PyInstaller runtime hook — fix StopIteration leak from importlib.metadata.

In a frozen PyInstaller app the dist-info metadata search can raise
StopIteration rather than PackageNotFoundError when a package is absent.
transformers' lazy import system only catches PackageNotFoundError, so the
StopIteration propagates and causes:

    ModuleNotFoundError: Could not import module 'pipeline'.

Wrapping Distribution.from_name (and the module-level alias) ensures any
StopIteration is immediately converted to PackageNotFoundError, which
transformers handles correctly.
"""
import importlib.metadata as _imeta

# Grab the bound classmethod before we patch it.
_orig_cls_from_name = _imeta.Distribution.from_name

def _safe_from_name(name):
    try:
        return _orig_cls_from_name(name)
    except StopIteration:
        raise _imeta.PackageNotFoundError(name)

# Patch at the Distribution class level so every internal call goes through
# the safe wrapper regardless of which call-site transformers uses.
_imeta.Distribution.from_name = staticmethod(_safe_from_name)

# The module-level alias is a separate name binding; patch it too.
_imeta.from_name = _safe_from_name

# ---------------------------------------------------------------------------
# TorchScript source-access fix
# ---------------------------------------------------------------------------
# torch.jit.script compiles functions by calling inspect.getsource(), which
# requires the original .py file on disk. PyInstaller compiles .py -> .pyc and
# the source paths (co_filename) point to the build-time venv, not _internal/.
# Replacing torch.jit.script with a no-op identity function here — before any
# ML package is imported — means @torch.jit.script decorators in vocos, f5_tts,
# etc. silently leave the functions as plain Python. Inference is unaffected.
try:
    import torch as _torch
    if not getattr(_torch.jit, '_narratible_noop', False):
        _torch.jit.script = lambda fn, *a, **kw: fn
        _torch.jit._narratible_noop = True
except Exception:
    pass
