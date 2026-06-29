"""Tests for the logging setup module."""

from __future__ import annotations

import logging
import sys
from unittest.mock import MagicMock, patch

import pytest

import logging_setup as ls


def test_setup_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(ls, "_CONFIGURED", False)
    monkeypatch.setattr(ls.os, "environ", {"APPDATA": str(tmp_path)})
    p1 = ls.setup()
    p2 = ls.setup()
    assert p1 == p2
    assert p1.parent.is_dir()


def test_setup_creates_log_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(ls, "_CONFIGURED", False)
    monkeypatch.setattr(ls.os, "environ", {"APPDATA": str(tmp_path)})
    p = ls.setup()
    assert p.parent.is_dir()
    assert p.parent.parent == tmp_path


def test_setup_falls_back_to_home_config(monkeypatch, tmp_path):
    monkeypatch.setattr(ls, "_CONFIGURED", False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(ls.os, "environ", {})
    monkeypatch.setattr(ls.Path, "home", lambda: tmp_path)
    p = ls.setup()
    assert "VolumeMixer" in str(p)


def test_setup_handles_oserror_on_file(monkeypatch, tmp_path, caplog):
    """When the rotating file handler can't be created, setup still succeeds."""
    monkeypatch.setattr(ls, "_CONFIGURED", False)
    monkeypatch.setattr(ls.os, "environ", {"APPDATA": str(tmp_path)})

    def _raise(*a, **kw):
        raise OSError("disk full")

    with patch.object(ls.logging.handlers, "RotatingFileHandler", side_effect=_raise):
        with caplog.at_level(logging.INFO):
            p = ls.setup()
    # Stream handler still set up so messages aren't lost.
    assert ls._CONFIGURED is True


def test_excepthook_installs_global(monkeypatch):
    original = sys.excepthook
    ls.install_excepthook()
    assert sys.excepthook is not original
    assert callable(sys.excepthook)
    # Restore
    sys.excepthook = original


def test_excepthook_handles_keyboard_interrupt(monkeypatch):
    called = {"n": 0}
    def _sys_hook(*a):
        called["n"] += 1
    monkeypatch.setattr(ls.sys, "__excepthook__", _sys_hook)
    ls.install_excepthook()
    try:
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt("ctrl-c"), None)
    finally:
        sys.excepthook = sys.__excepthook__
    assert called["n"] == 1


def test_excepthook_logs_unhandled(monkeypatch, tmp_path):
    monkeypatch.setattr(ls, "_CONFIGURED", False)
    monkeypatch.setattr(ls.os, "environ", {"APPDATA": str(tmp_path)})
    ls.setup()
    ls.install_excepthook()
    # Attach a memory handler to capture the excepthook's log emission.
    captured = []
    handler = logging.Handler()
    handler.emit = lambda record: captured.append(record)
    logger = logging.getLogger("uncaught")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        sys.excepthook(ValueError, ValueError("oops"), None)
    finally:
        sys.excepthook = sys.__excepthook__
        logger.removeHandler(handler)
    assert any("Uncaught exception" in r.getMessage() for r in captured)
    # The exception's message goes into exc_info, which is captured separately
    # by logging; assert it shows up in the formatted traceback.
    assert any(r.exc_info is not None for r in captured)
    assert any("oops" in (r.exc_info[1].args[0] if r.exc_info else "")
               for r in captured)
