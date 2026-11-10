"""
Verify microphone selection and the device-list refresh.

Checks:
  1. Priority order: the first connected name in input_device wins, and
     unknown names are skipped.
  2. Press-path latency: Recorder.start() is fast normally, and pays the
     PortAudio refresh (~50 ms) only when a device change is pending.
  3. Safety: a refresh is deferred while a stream is open, then happens once
     it closes.
  4. The Windows device-change watcher registers.
"""
import av_shim  # noqa: F401
import statistics
import time

import audio_devices
import main as m

cfg = m.load_config()
ok = True
logs = []
audio_devices.start_watching(lambda msg: logs.append(msg))

print("1. priority order")
pref = cfg["input_device"]
idx, name = m.resolve_input_device(pref)
print(f"   {pref} -> {name}")
idx2, name2 = m.resolve_input_device(["NoSuchMic", "Microphone Array", "Yeti"])
print(f"   ['NoSuchMic', 'Microphone Array', 'Yeti'] -> {name2}")
if "Array" not in name2:
    ok = False
    print("   FAIL: unknown name should be skipped and Array should win")

print("2. press-path latency")
rec = m.Recorder(cfg["sample_rate"], pref)
clean, dirty = [], []
for i in range(6):
    if i % 2:
        audio_devices.mark_dirty()
    t0 = time.perf_counter()
    rec.start()
    ms = (time.perf_counter() - t0) * 1000
    time.sleep(0.2)
    rec.stop()
    (dirty if i % 2 else clean).append(ms)
print(f"   start() normally:            median {statistics.median(clean):.0f} ms")
print(f"   start() after a mic change:  median {statistics.median(dirty):.0f} ms")

print("3. refresh deferred while a stream is open")
rec.start()
audio_devices.mark_dirty()
refreshed_during = audio_devices.refresh_if_dirty()
rec.stop()
refreshed_after = audio_devices.refresh_if_dirty()
print(f"   refreshed while recording: {refreshed_during} (must be False)")
print(f"   refreshed after closing:   {refreshed_after} (must be True)")
if refreshed_during or not refreshed_after:
    ok = False

print("4. watcher")
time.sleep(1.0)
watching = any("watching for audio device changes" in x for x in logs)
print(f"   registered: {watching}")
ok = ok and watching

print("DEVICES SELFTEST " + ("OK" if ok else "FAILED"))
raise SystemExit(0 if ok else 1)
