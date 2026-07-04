"""Tests for :mod:`single_instance` (mutex + named-pipe wake-up)."""

from __future__ import annotations

import sys
import threading
import time
import uuid
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _clear_mutex_handle():
    """Ensure no leftover mutex handle on config between tests."""
    import config
    if hasattr(config, "_SINGLE_INSTANCE_HANDLE"):
        del config._SINGLE_INSTANCE_HANDLE
    yield
    if hasattr(config, "_SINGLE_INSTANCE_HANDLE"):
        del config._SINGLE_INSTANCE_HANDLE


def test_acquire_mutex_first_call_true():
    """The first caller acquires the mutex and stores the handle on config."""
    import config
    import single_instance
    name = "Global\\VolumeMixerTest_" + uuid.uuid4().hex
    assert single_instance.acquire_mutex(name) is True
    assert hasattr(config, "_SINGLE_INSTANCE_HANDLE")
    assert config._SINGLE_INSTANCE_HANDLE is not None


def test_acquire_mutex_second_call_false():
    """A second caller for the same mutex name is rejected."""
    import single_instance
    name = "Global\\VolumeMixerTest_" + uuid.uuid4().hex
    assert single_instance.acquire_mutex(name) is True
    assert single_instance.acquire_mutex(name) is False


def test_acquire_mutex_non_windows_always_true():
    """On non-Windows the mutex acquisition is a no-op that returns True."""
    import single_instance
    with patch.object(single_instance, "_is_windows", return_value=False):
        assert single_instance.acquire_mutex("irrelevant") is True


def test_notify_no_server_returns_false():
    """Notifying when no server is listening returns False (no exception)."""
    import single_instance
    pipe = r"\\.\pipe\VolumeMixerNoServer_" + uuid.uuid4().hex
    assert single_instance.notify_running_instance(pipe) is False


def test_notify_non_windows_returns_false():
    import single_instance
    with patch.object(single_instance, "_is_windows", return_value=False):
        assert single_instance.notify_running_instance("x") is False


def test_pipe_server_round_trip():
    """End-to-end: server receives wake-up and invokes the callback."""
    import single_instance
    pipe = r"\\.\pipe\VolumeMixerRoundTrip_" + uuid.uuid4().hex
    event = threading.Event()
    server = single_instance.PipeServer()
    assert server.start(pipe, event.set) is True
    try:
        # Wait for the pipe to be created by the server thread.
        ok = False
        for _ in range(30):
            ok = single_instance.notify_running_instance(pipe)
            if ok:
                break
            time.sleep(0.05)
        assert ok, "notify_running_instance never succeeded"
        assert event.wait(timeout=3.0), "callback was not invoked"
    finally:
        server.stop()


def test_pipe_server_non_windows_noop():
    """On non-Windows start returns False and no thread is spawned."""
    import single_instance
    with patch.object(single_instance, "_is_windows", return_value=False):
        server = single_instance.PipeServer()
        assert server.start("x", lambda: None) is False
