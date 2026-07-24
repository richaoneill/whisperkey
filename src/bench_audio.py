"""
Audio-stream churn benchmark.

The app opens a fresh PortAudio InputStream for every dictation and closes it
on release. If that open/close cycle leaks handles or threads, the app would
get progressively slower the more it's used -- which is the reported symptom.

This exercises Recorder.start()/stop() repeatedly and tracks the cost.
"""
import av_shim  # noqa: F401
import ctypes
import threading
import time

import win32api
import win32process

import main as app_main

ROUNDS = 30
HOLD_S = 0.25

kernel32 = ctypes.windll.kernel32
kernel32.GetCurrentProcess.restype = ctypes.c_void_p


def rss_mb():
    info = win32process.GetProcessMemoryInfo(win32api.GetCurrentProcess())
    return info["WorkingSetSize"] / (1024 * 1024)


def handle_count():
    count = ctypes.c_ulong(0)
    ok = kernel32.GetProcessHandleCount(
        ctypes.c_void_p(kernel32.GetCurrentProcess()), ctypes.byref(count)
    )
    return count.value if ok else -1


def main():
    cfg = app_main.load_config()
    rec = app_main.Recorder(cfg["sample_rate"])

    print(f"{'rnd':>3} {'open_ms':>8} {'close_ms':>9} {'samples':>8} {'rss_mb':>8} {'handles':>8} {'threads':>8}")
    first = None
    for i in range(1, ROUNDS + 1):
        t0 = time.time()
        rec.start()
        open_ms = (time.time() - t0) * 1000

        time.sleep(HOLD_S)

        t1 = time.time()
        audio = rec.stop()
        close_ms = (time.time() - t1) * 1000

        stats = (open_ms, close_ms, len(audio), rss_mb(), handle_count(), threading.active_count())
        if first is None:
            first = stats
        print(
            f"{i:>3} {stats[0]:>8.0f} {stats[1]:>9.0f} {stats[2]:>8} "
            f"{stats[3]:>8.1f} {stats[4]:>8} {stats[5]:>8}"
        )

    print("\n--- trend (first -> last) ---")
    print(f"open_ms:  {first[0]:.0f} -> {stats[0]:.0f}")
    print(f"close_ms: {first[1]:.0f} -> {stats[1]:.0f}")
    print(f"rss_mb:   {first[3]:.1f} -> {stats[3]:.1f}   (delta {stats[3]-first[3]:+.1f} MB)")
    print(f"handles:  {first[4]} -> {stats[4]}   (delta {stats[4]-first[4]:+d})")
    print(f"threads:  {first[5]} -> {stats[5]}   (delta {stats[5]-first[5]:+d})")


if __name__ == "__main__":
    main()
