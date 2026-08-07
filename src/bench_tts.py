"""
Measure Piper synthesis throughput and chunk arrival timing.

Two symptoms to explain: a multi-second delay before speech starts, and audio
that skips between sentences. The numbers that matter are (a) how long the
first chunk takes to arrive, and (b) the realtime factor -- if synthesis only
just keeps ahead of playback, any hiccup starves the output and you hear a gap.
"""
import av_shim  # noqa: F401
import os
import time

import main as app_main

cfg = app_main.load_config()
model = cfg.get("tts_model")
if not os.path.isabs(model):
    model = os.path.join(os.path.dirname(__file__), "..", model)

from piper import PiperVoice

t0 = time.time()
voice = PiperVoice.load(model)
load_s = time.time() - t0
print(f"model load: {load_s:.2f}s  (paid once, on first F10 press today)")
print(f"config sample_rate: {getattr(voice.config, 'sample_rate', '?')}")

TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "Local speech synthesis has to keep ahead of playback or the audio stutters. "
    "This paragraph is deliberately several sentences long so we can watch how "
    "each chunk arrives relative to how long it takes to play. "
    "If the producer falls behind the consumer, you hear a gap. "
    "That is the difference between smooth speech and a scratched CD."
)

print(f"\nsynthesizing {len(TEXT)} chars...")
t0 = time.time()
first_at = None
total_samples = 0
sr = None
rows = []
for i, chunk in enumerate(voice.synthesize(TEXT), 1):
    now = time.time() - t0
    if first_at is None:
        first_at = now
    audio = chunk.audio_float_array
    sr = chunk.sample_rate
    total_samples += len(audio)
    rows.append((i, now, len(audio) / sr))

audio_s = total_samples / sr
synth_s = time.time() - t0

print(f"{'chunk':>5} {'arrived_at':>11} {'audio_len':>10} {'cumulative_audio':>17}")
cum = 0.0
for i, at, dur in rows:
    cum += dur
    flag = "  <-- STARVED" if at > cum else ""
    print(f"{i:>5} {at:>10.2f}s {dur:>9.2f}s {cum:>16.2f}s{flag}")

print(f"\nfirst audio available after: {first_at:.2f}s")
print(f"total synthesis: {synth_s:.2f}s for {audio_s:.2f}s of audio")
print(f"realtime factor: {audio_s / synth_s:.2f}x  (1.0 = only just keeping up)")
print(f"\ntime to first sound today = {load_s:.2f}s load + {first_at:.2f}s synth"
      f" = {load_s + first_at:.2f}s")
