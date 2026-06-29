"""WASAPI / pycaw based audio session controller.

Enumerates active audio sessions through pycaw, caches process metadata and
per-session ``ISimpleAudioVolume`` pointers, and exposes master + per-session
volume / mute controls. Threadsafe: COM callbacks are forwarded to the Qt
main thread before any controller state is touched.
"""

from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes
from typing import Any, Dict, List, Optional, Set, Union

import psutil
from comtypes import CoInitialize

from PyQt5.QtCore import QObject, pyqtSignal

from pycaw.pycaw import AudioUtilities
from pycaw.api.audiopolicy import IAudioSessionNotification
from pycaw.constants import AudioSessionState
import comtypes

import i18n

SessionKey = Union[str, int]
SessionDict = Dict[str, Any]

LOGGER = logging.getLogger(__name__)

COINIT_APARTMENTTHREADED = 0x2
COINIT_MULTITHREADED = 0x0
S_OK = 0
S_FALSE = 1
RPC_E_CHANGED_MODE = 0x80010106
shlwapi = ctypes.windll.shlwapi


class SessionNotificationSink(comtypes.COMObject):
    _com_interfaces_ = [IAudioSessionNotification]

    def __init__(self, controller: "AudioController"):
        super().__init__()
        self._controller = controller

    def IAudioSessionNotification_OnSessionCreated(self, this: Any, NewSession: Any) -> int:
        try:
            if self._controller:
                # Hop to the Qt main thread before touching the controller
                # or its caches; the COM callback may fire on a worker thread.
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(0, self._controller._on_session_created_sta)
        except Exception:
            LOGGER.exception("Session notification callback dispatch failed")
        return 0


def _resolve_indirect_string(s: Optional[str]) -> Optional[str]:
    if not s or not s.startswith('@'):
        return s
    try:
        buf = ctypes.create_unicode_buffer(1024)
        ret = shlwapi.SHLoadIndirectString(s, buf, 1024, None)
        if ret == 0 and buf.value:
            return buf.value
    except OSError:
        LOGGER.debug("SHLoadIndirectString OS error for %r", s)
    except Exception:
        LOGGER.exception("SHLoadIndirectString failed for %r", s)
    return s


def _get_friendly_name_cached(pid: int, proc: Optional[psutil.Process],
                              name_cache: Dict[int, str]) -> str:
    if pid in name_cache:
        return name_cache[pid]
    if proc is None:
        result = f"{i18n.UNKNOWN_PROCESS_PREFIX}{pid}"
        name_cache[pid] = result
        return result
    try:
        name = proc.name()
    except psutil.NoSuchProcess:
        result = f"{i18n.UNKNOWN_PROCESS_PREFIX}{pid}"
        name_cache[pid] = result
        return result
    except psutil.AccessDenied:
        name = str(pid)
        name_cache[pid] = name
        return name
    if name.lower().endswith('.exe'):
        name = name[:-4]
    try:
        exe_path = proc.exe()
    except psutil.NoSuchProcess:
        result = f"{i18n.UNKNOWN_PROCESS_PREFIX}{pid}"
        name_cache[pid] = result
        return result
    except psutil.AccessDenied:
        name_cache[pid] = name
        return name
    except OSError as exc:
        LOGGER.debug("exe() for pid %s raised OSError: %s", pid, exc)
        name_cache[pid] = name
        return name
    if exe_path and os.path.exists(exe_path):
        try:
            size = ctypes.windll.version.GetFileVersionInfoSizeW(exe_path, None)
            if size > 0:
                buf = ctypes.create_string_buffer(size)
                if ctypes.windll.version.GetFileVersionInfoW(exe_path, None, size, buf):
                    res = wintypes.LPWSTR()
                    res_len = wintypes.UINT()
                    for lang_codepage in ("080404B0", "040904B0", "000004B0"):
                        path = r"\StringFileInfo\{}\FileDescription".format(lang_codepage)
                        if ctypes.windll.version.VerQueryValueW(buf, path, ctypes.byref(res), ctypes.byref(res_len)):
                            if res.value and res.value.strip():
                                result = res.value.strip()
                                name_cache[pid] = result
                                return result
        except OSError as exc:
            LOGGER.debug("VersionInfo read for %s failed: %s", exe_path, exc)
    name_cache[pid] = name
    return name


class AudioController(QObject):
    session_changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._endpoint_volume: Any = None
        self._session_manager: Any = None
        self._device: Any = None
        self._notification_sink: Any = None
        self._sav_cache: Dict[SessionKey, Any] = {}
        self._name_cache: Dict[int, str] = {}
        self._com_initialized: bool = False
        self._shutdown_called: bool = False
        self._init_com()
        self._init_device()

    def _init_com(self) -> None:
        ole32 = ctypes.windll.ole32
        try:
            hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        except Exception:
            LOGGER.exception("CoInitializeEx raised unexpectedly")
            hr = None
        if hr == S_OK:
            self._com_initialized = True
            return
        if hr == S_FALSE:
            # Already initialized on this thread in the same apartment.
            # Don't call CoUninitialize in shutdown.
            LOGGER.debug("COM was already initialized in this apartment (S_FALSE)")
            return
        if hr == RPC_E_CHANGED_MODE:
            LOGGER.info("COM already initialized in different apartment, "
                        "falling back to CoInitialize()")
            try:
                CoInitialize()
                self._com_initialized = True
            except Exception:
                LOGGER.exception("CoInitialize fallback failed")
            return
        if hr is not None:
            LOGGER.warning("CoInitializeEx returned HRESULT 0x%08X", hr)
        try:
            CoInitialize()
            self._com_initialized = True
        except Exception:
            LOGGER.exception("CoInitialize fallback raised")

    def _init_device(self) -> None:
        try:
            self._device = AudioUtilities.GetSpeakers()
            if self._device is None:
                LOGGER.warning("AudioUtilities.GetSpeakers() returned None")
                return
            self._endpoint_volume = self._device.EndpointVolume
            self._session_manager = self._device.AudioSessionManager
            device_id = self._device.GetId() if hasattr(self._device, "GetId") else "?"
            LOGGER.info("Audio device initialized: %s", device_id)
        except Exception:
            LOGGER.exception("Audio device initialization failed")
            self._endpoint_volume = None
            self._session_manager = None

    def _ensure_endpoint(self) -> bool:
        """Make sure ``_endpoint_volume`` points to a working endpoint.

        Returns True if a valid endpoint is available. Re-initializes the
        device and re-registers the session callback when the original
        endpoint has been lost (e.g. default device hot-unplug).
        """
        if self._endpoint_volume is not None and self._device is not None:
            return True
        prev_session_manager = self._session_manager
        self._init_device()
        if self._endpoint_volume is None:
            return False
        if self._notification_sink is not None and self._session_manager is not prev_session_manager:
            try:
                if prev_session_manager is not None:
                    try:
                        prev_session_manager.UnregisterSessionNotification(self._notification_sink)
                    except Exception:
                        pass
                self._session_manager.RegisterSessionNotification(self._notification_sink)
                LOGGER.info("Re-registered session callback on new device")
            except Exception:
                LOGGER.exception("Failed to re-register session callback on new device")
        return True

    def register_session_callback(self) -> bool:
        if self._session_manager is None:
            return False
        try:
            if self._notification_sink is None:
                self._notification_sink = SessionNotificationSink(self)
            self._session_manager.RegisterSessionNotification(self._notification_sink)
            return True
        except comtypes.COMError as exc:
            LOGGER.warning("RegisterSessionNotification failed: %s", exc)
            return False
        except Exception:
            LOGGER.exception("RegisterSessionNotification failed unexpectedly")
            return False

    def unregister_session_callback(self) -> None:
        if self._session_manager is None or self._notification_sink is None:
            return
        try:
            self._session_manager.UnregisterSessionNotification(self._notification_sink)
        except comtypes.COMError as exc:
            LOGGER.debug("UnregisterSessionNotification COM error: %s", exc)
        except Exception:
            LOGGER.exception("UnregisterSessionNotification failed")

    def shutdown(self):
        """Release COM resources and unregister callbacks.

        Idempotent: safe to call multiple times.
        """
        if self._shutdown_called:
            return
        self._shutdown_called = True
        self.unregister_session_callback()
        self._sav_cache.clear()
        self._name_cache.clear()
        if self._com_initialized:
            try:
                ctypes.windll.ole32.CoUninitialize()
                LOGGER.info("COM uninitialized")
            except Exception:
                LOGGER.exception("CoUninitialize failed")
            self._com_initialized = False

    def _on_session_created_sta(self) -> None:
        self.session_changed.emit()

    def get_all_sessions(self) -> List[SessionDict]:
        sessions: List[SessionDict] = []
        new_sav_cache: Dict[SessionKey, Any] = {}
        try:
            raw_sessions = AudioUtilities.GetAllSessions()
        except comtypes.COMError as exc:
            LOGGER.warning("GetAllSessions COM error: %s", exc)
            raw_sessions = []
        except Exception:
            LOGGER.exception("GetAllSessions failed")
            raw_sessions = []

        current_pids: Set[int] = set()
        for s in raw_sessions:
            try:
                if s is None:
                    continue
                try:
                    state = s.State
                except comtypes.COMError as exc:
                    LOGGER.debug("Session State access failed: %s", exc)
                    continue
                if state == AudioSessionState.Expired:
                    continue

                try:
                    is_system = (s._ctl.IsSystemSoundsSession() == 0)
                except (comtypes.COMError, AttributeError) as exc:
                    LOGGER.debug("IsSystemSoundsSession failed: %s", exc)
                    is_system = False

                pid = s.ProcessId

                if is_system:
                    try:
                        disp_name = s.DisplayName
                    except comtypes.COMError as exc:
                        LOGGER.debug("System DisplayName access failed: %s", exc)
                        disp_name = ''
                    display_name = _resolve_indirect_string(disp_name) if disp_name else None
                    if not display_name:
                        display_name = i18n.SYSTEM_SOUNDS_NAME
                    try:
                        sav = s.SimpleAudioVolume
                        vol = round(sav.GetMasterVolume() * 100)
                        mute = bool(sav.GetMute())
                    except comtypes.COMError as exc:
                        LOGGER.debug("System session volume read failed: %s", exc)
                        vol = None
                        mute = False
                    sessions.append({
                        'key': 'system',
                        'pid': 0,
                        'display_name': display_name,
                        'volume': vol,
                        'mute': mute,
                        'is_system': True,
                    })
                    try:
                        new_sav_cache['system'] = s.SimpleAudioVolume
                    except comtypes.COMError:
                        pass
                    continue

                if pid in current_pids:
                    continue
                current_pids.add(pid)

                try:
                    proc = s.Process
                except (comtypes.COMError, psutil.NoSuchProcess) as exc:
                    LOGGER.debug("Process lookup for pid %s failed: %s", pid, exc)
                    proc = None
                except Exception:
                    LOGGER.exception("Unexpected error in Process lookup for pid %s", pid)
                    proc = None
                display_name = _get_friendly_name_cached(pid, proc, self._name_cache)

                try:
                    sav = s.SimpleAudioVolume
                    vol = round(sav.GetMasterVolume() * 100)
                    mute = bool(sav.GetMute())
                except comtypes.COMError as exc:
                    LOGGER.debug("Session volume read for pid %s failed: %s", pid, exc)
                    vol = None
                    mute = False

                sessions.append({
                    'key': pid,
                    'pid': pid,
                    'display_name': display_name,
                    'volume': vol,
                    'mute': mute,
                    'is_system': False,
                })
                try:
                    new_sav_cache[pid] = s.SimpleAudioVolume
                except comtypes.COMError:
                    pass
            except Exception:
                LOGGER.exception("Unexpected error processing audio session; skipping")
                continue

        sessions.sort(key=lambda x: (0 if x['is_system'] else 1, x['display_name'].lower()))
        self._cleanup_name_cache(current_pids)
        self._sav_cache = new_sav_cache
        return sessions

    def _cleanup_name_cache(self, current_pids: Set[int]) -> None:
        dead_pids = [pid for pid in self._name_cache if pid not in current_pids and pid != 0]
        for pid in dead_pids:
            del self._name_cache[pid]

    def get_master_volume(self) -> Optional[int]:
        if not self._ensure_endpoint():
            return None
        try:
            vol = self._endpoint_volume.GetMasterVolumeLevelScalar()
            return round(vol * 100)
        except comtypes.COMError as exc:
            LOGGER.warning("get_master_volume COM error: %s; invalidating endpoint", exc)
            self._endpoint_volume = None
            return None
        except Exception:
            LOGGER.exception("get_master_volume failed; invalidating endpoint")
            self._endpoint_volume = None
            return None

    def get_master_mute(self) -> Optional[bool]:
        if not self._ensure_endpoint():
            return None
        try:
            return bool(self._endpoint_volume.GetMute())
        except comtypes.COMError as exc:
            LOGGER.warning("get_master_mute COM error: %s; invalidating endpoint", exc)
            self._endpoint_volume = None
            return None
        except Exception:
            LOGGER.exception("get_master_mute failed; invalidating endpoint")
            self._endpoint_volume = None
            return None

    def set_master_volume(self, value: int) -> bool:
        if not self._ensure_endpoint():
            return False
        try:
            value = max(0, min(100, int(value)))
            self._endpoint_volume.SetMasterVolumeLevelScalar(value / 100.0, None)
            return True
        except comtypes.COMError as exc:
            LOGGER.warning("set_master_volume COM error: %s; invalidating endpoint", exc)
            self._endpoint_volume = None
            return False
        except Exception:
            LOGGER.exception("set_master_volume failed; invalidating endpoint")
            self._endpoint_volume = None
            return False

    def set_master_mute(self, mute: bool) -> bool:
        if not self._ensure_endpoint():
            return False
        try:
            self._endpoint_volume.SetMute(1 if mute else 0, None)
            return True
        except comtypes.COMError as exc:
            LOGGER.warning("set_master_mute COM error: %s; invalidating endpoint", exc)
            self._endpoint_volume = None
            return False
        except Exception:
            LOGGER.exception("set_master_mute failed; invalidating endpoint")
            self._endpoint_volume = None
            return False

    def set_volume_by_key(self, key: SessionKey, value: int) -> bool:
        try:
            value = max(0, min(100, int(value)))
        except (TypeError, ValueError):
            LOGGER.warning("set_volume_by_key: invalid value %r for key %r", value, key)
            return False
        if key == 'master':
            return self.set_master_volume(value)
        if key == 'system':
            return self._set_system_volume(value)
        if isinstance(key, int):
            return self._set_pid_volume(key, value)
        LOGGER.warning("set_volume_by_key: invalid key %r", key)
        return False

    def set_mute_by_key(self, key: SessionKey, mute: bool) -> bool:
        if key == 'master':
            return self.set_master_mute(mute)
        if key == 'system':
            return self._set_system_mute(mute)
        if isinstance(key, int):
            return self._set_pid_mute(key, mute)
        LOGGER.warning("set_mute_by_key: invalid key %r", key)
        return False

    def _get_sav_for_key(self, key: SessionKey) -> Any:
        if key in self._sav_cache:
            try:
                sav = self._sav_cache[key]
                sav.GetMasterVolume()
                return sav
            except comtypes.COMError as exc:
                LOGGER.debug("Cached SAV for %s stale (%s); refreshing", key, exc)
                del self._sav_cache[key]
            except Exception:
                LOGGER.exception("Cached SAV access for %s failed; refreshing", key)
                del self._sav_cache[key]

        try:
            raw_sessions = AudioUtilities.GetAllSessions()
        except comtypes.COMError as exc:
            LOGGER.warning("GetAllSessions COM error while resolving %s: %s", key, exc)
            return None
        except Exception:
            LOGGER.exception("GetAllSessions failed while resolving %s", key)
            return None

        for s in raw_sessions:
            try:
                if s is None:
                    continue
                try:
                    state = s.State
                except comtypes.COMError:
                    continue
                if state == AudioSessionState.Expired:
                    continue
                is_system = False
                try:
                    is_system = (s._ctl.IsSystemSoundsSession() == 0)
                except (comtypes.COMError, AttributeError):
                    pass
                if key == 'system' and is_system:
                    sav = s.SimpleAudioVolume
                    self._sav_cache[key] = sav
                    return sav
                if not is_system and s.ProcessId == key:
                    sav = s.SimpleAudioVolume
                    self._sav_cache[key] = sav
                    return sav
            except Exception:
                LOGGER.exception("Unexpected error while resolving SAV for %s", key)
                continue
        return None

    def _set_system_volume(self, value: int) -> bool:
        sav = self._get_sav_for_key('system')
        if sav is None:
            return False
        try:
            sav.SetMasterVolume(value / 100.0, None)
            return True
        except comtypes.COMError as exc:
            LOGGER.warning("SetMasterVolume for system failed: %s", exc)
            self._sav_cache.pop('system', None)
            return False
        except Exception:
            LOGGER.exception("SetMasterVolume for system failed unexpectedly")
            self._sav_cache.pop('system', None)
            return False

    def _set_system_mute(self, mute: bool) -> bool:
        sav = self._get_sav_for_key('system')
        if sav is None:
            return False
        try:
            sav.SetMute(1 if mute else 0, None)
            return True
        except comtypes.COMError as exc:
            LOGGER.warning("SetMute for system failed: %s", exc)
            self._sav_cache.pop('system', None)
            return False
        except Exception:
            LOGGER.exception("SetMute for system failed unexpectedly")
            self._sav_cache.pop('system', None)
            return False

    def _set_pid_volume(self, pid: int, value: int) -> bool:
        sav = self._get_sav_for_key(pid)
        if sav is None:
            return False
        try:
            sav.SetMasterVolume(value / 100.0, None)
            return True
        except comtypes.COMError as exc:
            LOGGER.warning("SetMasterVolume for pid %s failed: %s", pid, exc)
            self._sav_cache.pop(pid, None)
            return False
        except Exception:
            LOGGER.exception("SetMasterVolume for pid %s failed unexpectedly", pid)
            self._sav_cache.pop(pid, None)
            return False

    def _set_pid_mute(self, pid: int, mute: bool) -> bool:
        sav = self._get_sav_for_key(pid)
        if sav is None:
            return False
        try:
            sav.SetMute(1 if mute else 0, None)
            return True
        except comtypes.COMError as exc:
            LOGGER.warning("SetMute for pid %s failed: %s", pid, exc)
            self._sav_cache.pop(pid, None)
            return False
        except Exception:
            LOGGER.exception("SetMute for pid %s failed unexpectedly", pid)
            self._sav_cache.pop(pid, None)
            return False
