"""Windows compatibility for Hugging Face cache entries in frozen builds."""

import logging
import os
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _blob_target(snapshot_path: Path, snapshots_dir: Path) -> Path | None:
    """Return a validated blob target without traversing a reparse point."""
    repository_dir = snapshots_dir.parent
    if not repository_dir.name.startswith(("models--", "datasets--", "spaces--")):
        return None

    link_target = os.readlink(snapshot_path)
    if os.path.isabs(link_target):
        return None
    blob_path = Path(os.path.abspath(os.path.join(snapshot_path.parent, link_target)))
    try:
        blob_path.relative_to(repository_dir / "blobs")
    except ValueError:
        return None
    return blob_path if blob_path.is_file() else None


def materialize_snapshot_links(hub_cache: Path) -> int:
    """Replace Hugging Face snapshot symlinks with hard links to cache blobs."""
    materialized = 0
    if not hub_cache.is_dir():
        return materialized

    for snapshots_dir in hub_cache.glob("*--*/snapshots"):
        if not snapshots_dir.is_dir():
            continue
        for snapshot_path in snapshots_dir.rglob("*"):
            if not snapshot_path.is_symlink():
                continue
            blob_path = _blob_target(snapshot_path, snapshots_dir)
            if blob_path is None:
                continue
            try:
                snapshot_path.unlink()
                try:
                    os.link(blob_path, snapshot_path)
                except OSError:
                    shutil.copy2(blob_path, snapshot_path)
                materialized += 1
            except OSError as exc:
                logger.warning("Could not materialize Hugging Face cache file %s: %s", snapshot_path, exc)
    return materialized


def configure_frozen_huggingface_cache() -> None:
    """Use real files in the Windows cache before native model loaders run."""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return

    try:
        from huggingface_hub import constants
    except ImportError:
        return

    # Native safetensors/PyTorch loaders cannot follow some Windows cache links.
    # The hub copies future snapshot entries; existing entries are hard-linked above.
    constants.HF_HUB_DISABLE_SYMLINKS = True
    materialized = materialize_snapshot_links(Path(constants.HF_HUB_CACHE))
    if materialized:
        logger.info("Materialized %d Hugging Face cache files for the frozen app.", materialized)