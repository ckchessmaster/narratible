"""Tests for Hugging Face cache entries used by frozen native model loaders."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.hf_cache import materialize_snapshot_links  # noqa: E402


def test_materialize_snapshot_links_replaces_valid_blob_symlink(tmp_path):
    repository = tmp_path / "models--example--voice"
    blob = repository / "blobs" / "model"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"model bytes")
    snapshot = repository / "snapshots" / "revision" / "nested" / "model.safetensors"
    snapshot.parent.mkdir(parents=True)
    try:
        snapshot.symlink_to(os.path.relpath(blob, snapshot.parent))
    except OSError as exc:
        pytest.skip(f"Symlinks are unavailable in this environment: {exc}")

    assert materialize_snapshot_links(tmp_path) == 1
    assert not snapshot.is_symlink()
    assert snapshot.read_bytes() == b"model bytes"


def test_materialize_snapshot_links_rejects_external_symlink(tmp_path):
    repository = tmp_path / "models--example--voice"
    snapshot = repository / "snapshots" / "revision" / "model.safetensors"
    snapshot.parent.mkdir(parents=True)
    external_blob = tmp_path / "external-model"
    external_blob.write_bytes(b"outside")
    try:
        snapshot.symlink_to(external_blob)
    except OSError as exc:
        pytest.skip(f"Symlinks are unavailable in this environment: {exc}")

    assert materialize_snapshot_links(tmp_path) == 0
    assert snapshot.is_symlink()