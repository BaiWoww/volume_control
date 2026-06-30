"""Tests for the :mod:`main` entry-point helpers."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def with_qapp(qapp):
    """Reuse the session-level qapp fixture so the offscreen platform is set."""
    return qapp


def test_load_app_icon_is_nonempty(with_qapp):
    """The bundled icon.ico must be loadable and yield real pixmaps."""
    import main
    icon = main._load_app_icon()
    assert not icon.isNull()
    # A real ICO has at least one of the standard sizes.
    for size in (16, 32, 48, 64, 256):
        pm = icon.pixmap(size, size)
        assert not pm.isNull(), f"icon produced no pixmap at {size}px"
        assert pm.width() == size
        assert pm.height() == size


def test_assets_dir_falls_back_to_source_tree(monkeypatch):
    """When not frozen, _assets_dir points next to main.py."""
    import main
    monkeypatch.delattr(main.sys, "_MEIPASS", raising=False)
    d = main._assets_dir()
    assert d.name == "assets"
    assert d.parent == main.Path(main.__file__).resolve().parent


def test_assets_dir_uses_meipass_when_frozen(monkeypatch, tmp_path):
    """When frozen via PyInstaller, _assets_dir points at sys._MEIPASS/assets."""
    import main
    monkeypatch.setattr(main.sys, "_MEIPASS", str(tmp_path), raising=False)
    d = main._assets_dir()
    assert d == tmp_path / "assets"


def test_load_app_icon_handles_missing_file(monkeypatch, tmp_path):
    """If the .ico is missing the icon is empty (QIcon is not null but its
    pixmaps are null) — the app still launches without crashing."""
    import main
    # Repoint _assets_dir to an empty tmp dir.
    monkeypatch.setattr(main.sys, "_MEIPASS", str(tmp_path), raising=False)
    icon = main._load_app_icon()
    # No exception was raised; pixmaps are null because the file was missing.
    pm = icon.pixmap(64, 64)
    assert pm.isNull()


def test_acquire_single_instance_creates_mutex(with_qapp):
    """First call returns True and creates the handle on config."""
    import config
    import main
    # Ensure no leftover handle.
    if hasattr(config, "_SINGLE_INSTANCE_HANDLE"):
        del config._SINGLE_INSTANCE_HANDLE
    result = main._acquire_single_instance()
    assert result is True
    assert hasattr(config, "_SINGLE_INSTANCE_HANDLE")
