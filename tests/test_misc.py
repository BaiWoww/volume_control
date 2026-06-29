"""Additional edge-case and regression tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---- pyproject.toml validity --------------------------------------------

def test_pyproject_toml_is_valid():
    import tomllib
    p = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with p.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["project"]["name"] == "volumemixer"
    assert "PyQt5" in str(data["project"]["dependencies"])
    assert data["project"]["scripts"]["volumemixer"] == "main:main"


def test_requirements_txt_present_and_pinned():
    p = Path(__file__).resolve().parent.parent / "requirements.txt"
    text = p.read_text(encoding="utf-8")
    assert "PyQt5==" in text
    assert "pycaw==" in text


def test_readme_mentions_optional_dev_extras():
    p = Path(__file__).resolve().parent.parent / "README.md"
    text = p.read_text(encoding="utf-8")
    assert "Development" in text or "Testing" in text
    assert "pytest" in text
    assert "mypy" in text


def test_license_present():
    p = Path(__file__).resolve().parent.parent / "LICENSE"
    assert p.is_file()
    assert "MIT" in p.read_text(encoding="utf-8")


def test_gitignore_excludes_build_and_dist():
    p = Path(__file__).resolve().parent.parent / ".gitignore"
    text = p.read_text(encoding="utf-8")
    assert "build/" in text
    assert "dist/" in text
    assert "__pycache__/" in text


# ---- i18n coverage of known strings --------------------------------------

def test_panel_strings_present():
    import i18n
    # These specific phrases must exist; if anyone refactors the
    # i18n module, the test will catch accidental deletions.
    for phrase in ["音量合成器", "刷新", "应用程序", "系统主音量",
                   "系统声音", "已静音", "置顶", "退出"]:
        assert any(phrase in getattr(i18n, name, "")
                   for name in dir(i18n) if not name.startswith("_")), \
            f"Phrase {phrase!r} missing from i18n"


# ---- config load_overrides from real file --------------------------------

def test_load_overrides_from_real_file(tmp_path, monkeypatch):
    import config
    cfg = tmp_path / "VolumeMixer" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"panel_refresh_ms": 3000}), encoding="utf-8")
    # Override _config_path to return our tmp file.
    monkeypatch.setattr(config, "_config_path", lambda: cfg)
    result = config.load_overrides()
    assert result == {"panel_refresh_ms": 3000}


def test_load_overrides_malformed_json(tmp_path, monkeypatch, caplog):
    import logging
    import config
    cfg = tmp_path / "VolumeMixer" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("not valid json", encoding="utf-8")
    monkeypatch.setattr(config, "_config_path", lambda: cfg)
    with caplog.at_level(logging.WARNING):
        result = config.load_overrides()
    assert result == {}


def test_load_overrides_non_object_root(tmp_path, monkeypatch):
    import config
    cfg = tmp_path / "VolumeMixer" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    monkeypatch.setattr(config, "_config_path", lambda: cfg)
    assert config.load_overrides() == {}


def test_load_overrides_missing_file(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "_config_path",
                        lambda: tmp_path / "nope.json")
    assert config.load_overrides() == {}


# ---- Animation state during rapid toggle ---------------------------------

def test_panel_rapid_show_hide_no_orphan_animations(qapp):
    """Repeated show/hide must not leave orphan animations emitting later."""
    import volume_panel as vp

    class AC:
        def get_master_volume(self): return 50
        def get_master_mute(self): return False
        def get_all_sessions(self): return []

    panel = vp.VolumePanel(AC())
    emissions = []
    panel.panel_closed.connect(lambda: emissions.append(1))
    from PyQt5.QtCore import QPoint, QEventLoop, QTimer
    # Pump events between iterations so each animation can finish.
    for _ in range(3):
        panel.show_panel(QPoint(0, 0))
        loop = QEventLoop()
        QTimer.singleShot(300, loop.quit)
        loop.exec_()
        panel.hide_panel()
        loop = QEventLoop()
        QTimer.singleShot(300, loop.quit)
        loop.exec_()
    # 3 full cycles should yield exactly 3 emissions, no orphans.
    assert len(emissions) == 3, f"expected 3 emissions, got {len(emissions)}"
    panel.deleteLater()


# ---- Test suite self-checks ----------------------------------------------

def test_all_modules_have_docstrings():
    """Every top-level module should have a non-empty docstring."""
    for name in ("config", "i18n", "logging_setup", "hotkey",
                 "audio_controller", "floating_ball", "volume_panel", "main"):
        mod = __import__(name)
        assert getattr(mod, "__doc__", None), f"{name} has no docstring"
        assert mod.__doc__.strip(), f"{name} docstring is empty"
