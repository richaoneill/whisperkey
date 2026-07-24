"""
Corrected transcription benchmark.

bench.py used synthetic noise, which the VAD filter discarded as non-speech --
so it never actually ran the model. This forces real decoding work
(vad_filter=False) so latency/memory trends are measured honestly.
"""
import av_shim  # noqa: F401
import ctypes
import threading
import time

import numpy as np
import win32api
import win32process
from faster_whisper import WhisperModel

import main as app_main

ROUNDS = 20
AUDIO_SECONDS = 5

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


def speechlike(sr, seconds):
    """Amplitude-modulated harmonic tone -- forces the decoder to do real work."""
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    sig = np.zeros_like(t)
    for f in (120, 240, 360, 480):
        sig += np.sin(2 * np.pi * f * t) / (f / 120)
    envelope = 0.5 * (1 + np.sin(2 * np.pi * 3 * t))  # ~3 Hz syllable rate
    return (0.2 * sig * envelope).astype(np.float32)


def main():
    cfg = app_main.load_config()
    print(f"loading model {cfg['model_size']}...")
    model = WhisperModel(
        cfg["model_size"], device=cfg["device"], compute_type=cfg["compute_type"]
    )
    audio = speechlike(cfg["sample_rate"], AUDIO_SECONDS)
    print(f"audio: {AUDIO_SECONDS}s, vad_filter=False (forcing real decode)\n")

    print(f"{'rnd':>3} {'stt_ms':>8} {'rss_mb':>8} {'handles':>8} {'threads':>8}")
    first = None
    times = []
    for i in range(1, ROUNDS + 1):
        t0 = time.time()
        segments, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=False)
        _ = "".join(s.text for s in segments)
        stt_ms = (time.time() - t0) * 1000
        times.append(stt_ms)

        stats = (stt_ms, rss_mb(), handle_count(), threading.active_count())
        if first is None:
            first = stats
        print(f"{i:>3} {stats[0]:>8.0f} {stats[1]:>8.1f} {stats[2]:>8} {stats[3]:>8}")

    half = len(times) // 2
    print("\n--- trend ---")
    print(f"first half avg stt_ms: {sum(times[:half])/half:.0f}")
    print(f"last  half avg stt_ms: {sum(times[half:])/(len(times)-half):.0f}")
    print(f"rss_mb:  {first[1]:.1f} -> {stats[1]:.1f}   (delta {stats[1]-first[1]:+.1f} MB)")
    print(f"handles: {first[2]} -> {stats[2]}   (delta {stats[2]-first[2]:+d})")


if __name__ == "__main__":
    main()
