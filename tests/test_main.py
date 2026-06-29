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


def test_build_app_icon_is_nonempty(with_qapp):
    """The procedural icon must produce pixmaps for every registered size."""
    import main
    icon = main._build_app_icon()
    assert not icon.isNull()
    for size in (16, 32, 48, 64, 256):
        pm = icon.pixmap(size, size)
        assert not pm.isNull()
        assert pm.width() == size
        assert pm.height() == size


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
