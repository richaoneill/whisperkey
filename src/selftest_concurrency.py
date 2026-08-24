"""
Verify a second dictation is not lost while the first is still transcribing.

Before the fix, _on_release() transcribed inline, blocking the hotkey worker.
A press during a long decode was silently swallowed: no beep, no recording,
no log line. This drives two releases back to back against a deliberately slow
model and checks both are transcribed.
"""
import av_shim  # noqa: F401
import threading
import time

import numpy as np

import main as app_main

DECODE_S = 3.0


class SlowModel:
    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def transcribe(self, audio, **kwargs):
        with self._lock:
            self.calls += 1
        time.sleep(DECODE_S)
        return ([], None)


class FakeRecorder:
    def __init__(self, sample_rate, seconds=2.0):
        self.sample_rate = sample_rate
        self.recording = False
        self._audio = np.zeros(int(sample_rate * seconds), dtype=np.float32)

    def start(self):
        self.recording = True

    def stop(self):
        self.recording = False
        return self._audio


cfg = app_main.load_config()
cfg["beep_feedback"] = False          # keep the test quiet
cfg["tts_enabled"] = False            # not under test here

model = SlowModel()
app = app_main.App(cfg, model)
app.recorder = FakeRecorder(cfg["sample_rate"])
app.muter = None
app.set_icon_state = lambda _s: None
app.set_recording_icon = lambda _b: None
app_main.inject_text = lambda _t, _c: None   # don't type into the real desktop

threading.Thread(target=app.stt_worker, daemon=True).start()

print(f"model decode time: {DECODE_S}s per utterance")

t0 = time.time()
app._on_release()
first_ms = (time.time() - t0) * 1000

t1 = time.time()
app._on_release()
second_ms = (time.time() - t1) * 1000

print(f"_on_release #1 returned in {first_ms:.0f}ms")
print(f"_on_release #2 returned in {second_ms:.0f}ms")
released_fast = first_ms < 500 and second_ms < 500
print(f"both returned immediately (not blocked by decode): {released_fast}")

# Wait long enough for both decodes to finish serially.
deadline = time.time() + DECODE_S * 2 + 4
while time.time() < deadline and model.calls < 2:
    time.sleep(0.1)

print(f"transcribe calls: {model.calls} (expected 2, neither press lost)")

app.stop_event.set()
app._stt_queue.put(None)

ok = released_fast and model.calls == 2
print("CONCURRENCY SELFTEST " + ("OK" if ok else "FAILED"))
raise SystemExit(0 if ok else 1)
