"""
Keep PortAudio's view of the audio devices current, cheaply.

PortAudio reads the device list once, at initialisation, so a microphone
plugged in or unplugged after launch was invisible until the app restarted.
Re-initialising PortAudio fixes that but costs about 50 ms, which is too much
to pay on every keypress: it sits between the press and the start of
recording and can clip the first word.

So Windows tells us when an audio endpoint is added, removed or changes state
(IMMNotificationClient via pycaw). The callback only sets a flag; a small
background thread waits a moment for the burst of events a plug-in produces to
settle, then refreshes while nothing is recording or playing. The keypress
path pays nothing unless it races a change, in which case it refreshes once.

Re-initialising PortAudio while a stream is open would break that stream, so
every stream open/close goes through PA_LOCK and an open-stream count, and a
refresh is deferred while any stream is live.
"""

import threading
import time

import sounddevice as sd

PA_LOCK = threading.RLock()
_dirty = threading.Event()
_open_streams = 0
_log = lambda _m: None  # noqa: E731
_watcher_refs = []      # keep COM objects alive for the life of the process


def stream_opened():
    global _open_streams
    with PA_LOCK:
        _open_streams += 1


def stream_closed():
    global _open_streams
    with PA_LOCK:
        _open_streams = max(0, _open_streams - 1)


def mark_dirty():
    _dirty.set()


def refresh_if_dirty():
    """Re-read the device list if Windows reported a change and it is safe.

    Returns True if a refresh happened. Leaves the flag set (so it is retried)
    when a stream is open.
    """
    if not _dirty.is_set():
        return False
    with PA_LOCK:
        if not _dirty.is_set() or _open_streams > 0:
            return False
        _dirty.clear()
        t0 = time.perf_counter()
        try:
            sd._terminate()
            sd._initialize()
        except Exception as e:
            _log(f"audio device refresh failed: {e}")
            return False
        _log(f"audio devices changed; device list refreshed in "
             f"{(time.perf_counter() - t0) * 1000:.0f} ms")
        return True


def _refresher():
    while True:
        _dirty.wait()
        time.sleep(1.0)          # a plug-in fires several events; let them settle
        while _dirty.is_set() and not refresh_if_dirty():
            time.sleep(1.0)      # a stream is open; retry when it closes


def start_watching(log=None):
    """Subscribe to Windows audio endpoint changes. Safe to call once."""
    global _log
    if log:
        _log = log

    def run():
        try:
            import comtypes
            from pycaw.callbacks import MMNotificationClient
            from pycaw.pycaw import AudioUtilities

            class _Client(MMNotificationClient):
                def on_device_added(self, *args, **kwargs):
                    mark_dirty()

                def on_device_removed(self, *args, **kwargs):
                    mark_dirty()

                def on_device_state_changed(self, *args, **kwargs):
                    mark_dirty()

                def on_default_device_changed(self, *args, **kwargs):
                    mark_dirty()

            # Prefer a multithreaded apartment. comtypes initialises a thread
            # as single-threaded the moment it is first imported there, in
            # which case Windows refuses to change mode (RPC_E_CHANGED_MODE).
            # That's fine: MMDevice calls IMMNotificationClient on its own
            # threads, and the message pump below covers the STA case.
            try:
                comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            except OSError:
                pass
            enumerator = AudioUtilities.GetDeviceEnumerator()
            client = _Client()
            enumerator.RegisterEndpointNotificationCallback(client)
            _watcher_refs.extend([enumerator, client])
            _log("watching for audio device changes")
        except Exception as e:
            _log(f"audio device watcher unavailable ({e}); "
                 "mic changes need an app restart")
            return
        try:
            import pythoncom
            pythoncom.PumpMessages()   # keep the apartment alive and serviced
        except Exception:
            threading.Event().wait()

    threading.Thread(target=run, daemon=True).start()
    threading.Thread(target=_refresher, daemon=True).start()
