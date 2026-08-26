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
