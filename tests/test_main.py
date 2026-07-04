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


def test_main_exits_when_second_instance(with_qapp, monkeypatch):
    """When the mutex is already held, main() notifies the running
    instance and exits with code 0."""
    import main
    monkeypatch.setattr(main.single_instance, "acquire_mutex", lambda name: False)
    called = {"notify": False}

    def fake_notify(pipe):
        called["notify"] = True
        return True

    monkeypatch.setattr(main.single_instance, "notify_running_instance", fake_notify)
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 0
    assert called["notify"] is True


def test_main_starts_pipe_server_for_first_instance(with_qapp, monkeypatch):
    """When the mutex is acquired, main() starts the pipe server."""
    import main
    monkeypatch.setattr(main.single_instance, "acquire_mutex", lambda name: True)
    monkeypatch.setattr(main, "AudioController", MagicMock())
    monkeypatch.setattr(main, "FloatingBall", MagicMock())

    started = {"pipe": False}

    class FakePipeServer:
        def start(self, pipe_name, on_show):
            started["pipe"] = True
            return True

        def stop(self):
            pass

    monkeypatch.setattr(main.single_instance, "PipeServer", FakePipeServer)

    # Replace QApplication with a mock so main() never touches the real
    # Qt application (which is shared via the qapp fixture and must not be
    # re-initialised or have its style/icon changed mid-suite).
    mock_app = MagicMock()
    mock_app.exec_.return_value = 0
    mock_qapp = MagicMock(return_value=mock_app)
    monkeypatch.setattr(main, "QApplication", mock_qapp)

    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 0
    assert started["pipe"] is True
