"""
Read the current selection aloud, locally.

Windows has no API for adding an item to every app's text context menu -- each
application draws its own -- so this uses the same universal mechanism as
dictation: a global hotkey. Press it and the current selection is copied with
Ctrl+C, spoken, and your clipboard is put back.

Two engines, both fully offline:

  "windows"  Built-in SAPI voices via pywin32. No download, no extra license
             obligations. Robotic but instant. This is the default.

  "piper"    Neural voice, markedly more natural. Opt-in, because piper-tts is
             GPL-3.0-or-later (it bundles espeak-ng) -- see LICENSE notes in the
             README before redistributing a bundle that includes it.

Piper playback synthesizes ahead of playback on a producer thread so sentences
don't stutter, and both engines poll a stop flag so a second keypress
interrupts immediately rather than at the end of the current sentence.
"""

import os
import queue
import threading
import time

import keyboard
import pyperclip
import sounddevice as sd

_SENTINEL = object()

# SAPI SpeechVoiceSpeakFlags
_SVSF_ASYNC = 1
_SVSF_PURGE = 2


def get_selected_text(timeout_s=0.6):
    """Copy the current selection without permanently disturbing the clipboard.

    Clears the clipboard first so an empty result reliably means "nothing was
    selected" rather than "the selection happened to match what was already
    there". The previous contents are restored on a short delay.
    """
    saved = None
    try:
        saved = pyperclip.paste()
    except Exception:
        saved = None

    try:
        pyperclip.copy("")
    except Exception:
        pass

    keyboard.send("ctrl+c")

    text = ""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(0.03)
        try:
            text = pyperclip.paste()
        except Exception:
            text = ""
        if text:
            break

    if saved is not None:
        def _restore():
            time.sleep(0.25)
            try:
                pyperclip.copy(saved)
            except Exception:
                pass

        threading.Thread(target=_restore, daemon=True).start()

    return (text or "").strip()


class Speaker:
    """Speech with interruptible playback, backed by Windows SAPI or Piper."""

    def __init__(self, model_path=None, speed=1.0, log=None, engine="auto"):
        self.model_path = str(model_path) if model_path else None
        self.speed = speed
        self._log = log or (lambda _m: None)
        self._voice = None
        self._load_lock = threading.Lock()
        self._stop = threading.Event()
        self._speaking = threading.Event()
        self._sapi = None
        self.engine = self._resolve_engine(engine)
        self._log(f"tts engine: {self.engine}")

    def _resolve_engine(self, requested):
        if requested == "windows":
            return "windows"

        model_ok = bool(self.model_path) and os.path.exists(self.model_path)
        if requested == "piper":
            if not model_ok:
                self._log("tts: piper requested but model missing; using windows")
                return "windows"
            return "piper"

        # auto: prefer piper only if it is both installed and has a voice model.
        if model_ok:
            try:
                import piper  # noqa: F401
                return "piper"
            except Exception:
                pass
        return "windows"

    @property
    def speaking(self):
        return self._speaking.is_set()

    def stop(self):
        """Interrupt playback. Safe from a keyboard hook -- never blocks."""
        self._stop.set()
        if self.engine == "piper":
            try:
                sd.stop()
            except Exception:
                pass
        else:
            try:
                if self._sapi is not None:
                    self._sapi.Speak("", _SVSF_PURGE)
            except Exception:
                pass

    def speak(self, text, max_chars=20000):
        if not text:
            return
        if len(text) > max_chars:
            text = text[:max_chars]
            self._log(f"tts: text truncated to {max_chars} chars")

        self._stop.clear()
        self._speaking.set()
        t0 = time.time()
        try:
            if self.engine == "piper":
                played = self._speak_piper(text)
            else:
                played = self._speak_windows(text)
            note = " (stopped)" if self._stop.is_set() else ""
            self._log(
                f"tts[{self.engine}]: {len(text)} chars, {played}, "
                f"{time.time() - t0:.1f}s{note}"
            )
        finally:
            self._speaking.clear()
            if self.engine == "piper":
                try:
                    sd.stop()
                except Exception:
                    pass

    # ---------- Windows SAPI ----------

    def _speak_windows(self, text):
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        if self._sapi is None:
            self._sapi = win32com.client.Dispatch("SAPI.SpVoice")
        # SAPI rate is -10..10; map speed 1.0 -> 0, 1.2 -> +1, 0.8 -> -1.
        try:
            rate = int(round((float(self.speed) - 1.0) * 5))
            self._sapi.Rate = max(-10, min(10, rate))
        except Exception:
            pass

        self._sapi.Speak(text, _SVSF_ASYNC)
        while not self._sapi.WaitUntilDone(100):
            if self._stop.is_set():
                try:
                    self._sapi.Speak("", _SVSF_PURGE)
                except Exception:
                    pass
                return "interrupted"
        return "complete"

    # ---------- Piper ----------

    def _load_piper(self):
        with self._load_lock:
            if self._voice is None:
                from piper import PiperVoice

                t0 = time.time()
                self._voice = PiperVoice.load(self.model_path)
                self._log(f"tts model loaded in {time.time() - t0:.1f}s")
        return self._voice

    def _piper_config(self):
        try:
            from piper import SynthesisConfig

            if self.speed and float(self.speed) != 1.0:
                # length_scale is inverse: >1 stretches audio out (slower).
                return SynthesisConfig(length_scale=1.0 / float(self.speed))
        except Exception:
            pass
        return None

    def _play_interruptible(self, audio, sample_rate):
        """Play one chunk, returning False if stop() was called."""
        sd.play(audio, samplerate=sample_rate)
        while True:
            if self._stop.is_set():
                try:
                    sd.stop()
                except Exception:
                    pass
                return False
            try:
                stream = sd.get_stream()
                if stream is None or not stream.active:
                    return True
            except Exception:
                return True
            time.sleep(0.03)

    def _speak_piper(self, text):
        voice = self._load_piper()
        cfg = self._piper_config()
        chunks = queue.Queue(maxsize=8)

        def produce():
            # Synthesize ahead of playback so sentences run together smoothly.
            try:
                gen = voice.synthesize(text, cfg) if cfg else voice.synthesize(text)
                for chunk in gen:
                    if self._stop.is_set():
                        break
                    chunks.put((chunk.audio_float_array, chunk.sample_rate))
            except Exception as e:
                self._log(f"tts synth error: {e}")
            finally:
                chunks.put(_SENTINEL)

        threading.Thread(target=produce, daemon=True).start()

        played = 0
        while not self._stop.is_set():
            item = chunks.get()
            if item is _SENTINEL:
                break
            audio, sample_rate = item
            if not self._play_interruptible(audio, sample_rate):
                break
            played += 1
        return f"{played} chunks"
