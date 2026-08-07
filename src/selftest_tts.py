"""Headless check for the TTS path: both engines, speak and interrupt.

Plays audio, so it doubles as an audible comparison of the two voices.
Does not exercise get_selected_text() -- that sends Ctrl+C to whatever window
has focus, which is rude to run unattended.
"""
import av_shim  # noqa: F401
import os
import threading
import time

import main as app_main
from tts import Speaker

cfg = app_main.load_config()
model = cfg.get("tts_model")
if not os.path.isabs(model):
    model = os.path.join(os.path.dirname(__file__), "..", model)
print("piper model present:", os.path.exists(model))

# Two separate passages. Reusing one for both tests was confusing: the
# smooth-playback test plays everything by design, so interrupt-flavoured
# wording ("this should never be reached") sounded like a bug when it played.
SMOOTH = (
    "This passage checks that playback runs continuously. "
    "Each sentence should follow the last without a gap or a click. "
    "If you hear stuttering between these sentences, the audio stream is being "
    "torn down and reopened instead of running straight through. "
    "This is the end of the smooth playback check."
)

INTERRUPT = (
    "This passage is meant to be cut off part way through. "
    "It keeps going for a while so there is time to stop it. "
    "You should stop hearing this within a couple of seconds. "
    "If you hear this last sentence, the stop control did not work."
)

for engine in ("windows", "piper"):
    print(f"\n=== engine: {engine} ===")
    sp = Speaker(model, cfg.get("tts_speed", 1.0), log=lambda m: print("  log:", m),
                 engine=engine)
    if sp.engine != engine:
        print(f"  resolved to '{sp.engine}' instead — skipping")
        continue

    t0 = time.time()
    sp.speak(f"Read aloud is working using the {engine} engine.")
    print(f"  short phrase: {time.time() - t0:.1f}s, flag cleared: {not sp.speaking}")

    # Smooth playback: must run gapless across sentence boundaries. Plays in
    # full on purpose -- listen for stutter, which was the "scratched CD" bug.
    print("  [1/2] smooth playback — plays in FULL, listen for gaps...")
    t0 = time.time()
    sp.speak(SMOOTH)
    full_s = time.time() - t0
    print(f"        played to completion in {full_s:.1f}s")

    # Interrupt: same-length passage, cut off after ~1.2s.
    print("  [2/2] interrupt — should cut off almost immediately...")
    t0 = time.time()
    threading.Thread(target=lambda: sp.speak(INTERRUPT), daemon=True).start()
    time.sleep(1.2)
    mid = sp.speaking
    sp.stop()
    time.sleep(0.5)
    stopped_s = time.time() - t0
    print(f"        speaking mid-passage={mid}, stopped after {stopped_s:.1f}s, "
          f"flag cleared={not sp.speaking}")
    print(f"        -> cut off at {stopped_s:.1f}s vs {full_s:.1f}s uninterrupted")

print("\nTTS SELFTEST OK")
