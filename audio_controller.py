import ctypes
import os
from ctypes import wintypes

import psutil
from comtypes import CoInitialize

from PyQt5.QtCore import QObject, pyqtSignal

from pycaw.pycaw import AudioUtilities
from pycaw.api.audiopolicy import IAudioSessionNotification
import comtypes

COINIT_APARTMENTTHREADED = 0x2
COINIT_MULTITHREADED = 0x0
shlwapi = ctypes.windll.shlwapi


class SessionNotificationSink(comtypes.COMObject):
    _com_interfaces_ = [IAudioSessionNotification]

    def __init__(self, controller):
        super().__init__()
        self._controller = controller

    def IAudioSessionNotification_OnSessionCreated(self, this, NewSession):
        try:
            if self._controller:
                self._controller._on_session_created_sta()
        except Exception:
            pass
        return 0


def _resolve_indirect_string(s):
    if not s or not s.startswith('@'):
        return s
    try:
        buf = ctypes.create_unicode_buffer(1024)
        ret = shlwapi.SHLoadIndirectString(s, buf, 1024, None)
        if ret == 0 and buf.value:
            return buf.value
    except Exception:
        pass
    return s


def _get_friendly_name_cached(pid, proc, name_cache):
    if pid in name_cache:
        return name_cache[pid]
    try:
        if proc is None:
            result = f"进程 {pid}"
            name_cache[pid] = result
            return result
        name = proc.name()
        if name.lower().endswith('.exe'):
            name = name[:-4]
        try:
            exe_path = proc.exe()
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
                except Exception:
                    pass
        except (psutil.AccessDenied, psutil.NoSuchProcess, Exception):
            pass
        name_cache[pid] = name
        return name
    except (psutil.NoSuchProcess, Exception):
        result = f"进程 {pid}"
        name_cache[pid] = result
        return result


class AudioController(QObject):
    session_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._endpoint_volume = None
        self._session_manager = None
        self._device = None
        self._notification_sink = None
        self._sav_cache = {}
        self._name_cache = {}
        self._init_com()
        self._init_device()

    def _init_com(self):
        try:
            ctypes.windll.ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        except Exception:
            try:
                CoInitialize()
            except Exception:
                pass

    def _init_device(self):
        try:
            self._device = AudioUtilities.GetSpeakers()
            if self._device is None:
                return
            self._endpoint_volume = self._device.EndpointVolume
            self._session_manager = self._device.AudioSessionManager
        except Exception:
            self._endpoint_volume = None
            self._session_manager = None

    def register_session_callback(self):
        if self._session_manager is None:
            return False
        try:
            if self._notification_sink is None:
                self._notification_sink = SessionNotificationSink(self)
            self._session_manager.RegisterSessionNotification(self._notification_sink)
            return True
        except Exception:
            return False

    def unregister_session_callback(self):
        if self._session_manager is None or self._notification_sink is None:
            return
        try:
            self._session_manager.UnregisterSessionNotification(self._notification_sink)
        except Exception:
            pass

    def _on_session_created_sta(self):
        self.session_changed.emit()

    def get_all_sessions(self):
        sessions = []
        try:
            raw_sessions = AudioUtilities.GetAllSessions()
        except Exception:
            raw_sessions = []

        current_pids = set()
        for s in raw_sessions:
            try:
                if s is None:
                    continue
                try:
                    state = s.State
                except Exception:
                    continue
                if state == 2:
                    continue

                try:
                    is_system = (s._ctl.IsSystemSoundsSession() == 0)
                except Exception:
                    is_system = False

                pid = s.ProcessId

                if is_system:
                    try:
                        disp_name = s.DisplayName
                    except Exception:
                        disp_name = ''
                    display_name = _resolve_indirect_string(disp_name) if disp_name else None
                    if not display_name:
                        display_name = "系统声音"
                    try:
                        sav = s.SimpleAudioVolume
                        vol = round(sav.GetMasterVolume() * 100)
                        mute = bool(sav.GetMute())
                    except Exception:
                        vol = 100
                        mute = False
                    sessions.append({
                        'key': 'system',
                        'pid': 0,
                        'display_name': display_name,
                        'volume': vol,
                        'mute': mute,
                        'is_system': True,
                        '_session': s,
                    })
                    continue

                if pid in current_pids:
                    continue
                current_pids.add(pid)

                try:
                    proc = s.Process
                except Exception:
                    proc = None
                display_name = _get_friendly_name_cached(pid, proc, self._name_cache)

                try:
                    sav = s.SimpleAudioVolume
                    vol = round(sav.GetMasterVolume() * 100)
                    mute = bool(sav.GetMute())
                except Exception:
                    vol = 80
                    mute = False

                sessions.append({
                    'key': pid,
                    'pid': pid,
                    'display_name': display_name,
                    'volume': vol,
                    'mute': mute,
                    'is_system': False,
                    '_session': s,
                })
            except Exception:
                continue

        sessions.sort(key=lambda x: (0 if x['is_system'] else 1, x['display_name'].lower()))
        self._cleanup_name_cache(current_pids)
        return sessions

    def _cleanup_name_cache(self, current_pids):
        dead_pids = [pid for pid in self._name_cache if pid not in current_pids and pid != 0]
        for pid in dead_pids:
            del self._name_cache[pid]

    def get_master_volume(self):
        try:
            if self._endpoint_volume is not None:
                vol = self._endpoint_volume.GetMasterVolumeLevelScalar()
                return round(vol * 100)
            self._init_device()
            if self._endpoint_volume is not None:
                vol = self._endpoint_volume.GetMasterVolumeLevelScalar()
                return round(vol * 100)
        except Exception:
            pass
        return 80

    def get_master_mute(self):
        try:
            if self._endpoint_volume is not None:
                return bool(self._endpoint_volume.GetMute())
        except Exception:
            pass
        return False

    def set_master_volume(self, value):
        try:
            value = max(0, min(100, int(value)))
            if self._endpoint_volume is not None:
                self._endpoint_volume.SetMasterVolumeLevelScalar(value / 100.0, None)
                return True
        except Exception:
            pass
        return False

    def set_master_mute(self, mute):
        try:
            if self._endpoint_volume is not None:
                self._endpoint_volume.SetMute(1 if mute else 0, None)
                return True
        except Exception:
            pass
        return False

    def set_volume_by_key(self, key, value):
        try:
            value = max(0, min(100, int(value)))
            if key == 'master':
                return self.set_master_volume(value)
            if key == 'system':
                return self._set_system_volume(value)
            return self._set_pid_volume(key, value)
        except Exception:
            return False

    def set_mute_by_key(self, key, mute):
        try:
            if key == 'master':
                return self.set_master_mute(mute)
            if key == 'system':
                return self._set_system_mute(mute)
            return self._set_pid_mute(key, mute)
        except Exception:
            return False

    def _get_sav_for_key(self, key):
        if key in self._sav_cache:
            try:
                sav = self._sav_cache[key]
                sav.GetMasterVolume()
                return sav
            except Exception:
                del self._sav_cache[key]

        try:
            raw_sessions = AudioUtilities.GetAllSessions()
        except Exception:
            return None

        for s in raw_sessions:
            try:
                if s is None:
                    continue
                is_system = False
                try:
                    is_system = (s._ctl.IsSystemSoundsSession() == 0)
                except Exception:
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
                continue
        return None

    def _set_system_volume(self, value):
        sav = self._get_sav_for_key('system')
        if sav is None:
            return False
        try:
            sav.SetMasterVolume(value / 100.0, None)
            return True
        except Exception:
            if 'system' in self._sav_cache:
                del self._sav_cache['system']
            return False

    def _set_system_mute(self, mute):
        sav = self._get_sav_for_key('system')
        if sav is None:
            return False
        try:
            sav.SetMute(1 if mute else 0, None)
            return True
        except Exception:
            if 'system' in self._sav_cache:
                del self._sav_cache['system']
            return False

    def _set_pid_volume(self, pid, value):
        sav = self._get_sav_for_key(pid)
        if sav is None:
            return False
        try:
            sav.SetMasterVolume(value / 100.0, None)
            return True
        except Exception:
            if pid in self._sav_cache:
                del self._sav_cache[pid]
            return False

    def _set_pid_mute(self, pid, mute):
        sav = self._get_sav_for_key(pid)
        if sav is None:
            return False
        try:
            sav.SetMute(1 if mute else 0, None)
            return True
        except Exception:
            if pid in self._sav_cache:
                del self._sav_cache[pid]
            return False
