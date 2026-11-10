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

import collections
import os
import threading
import time

import keyboard
import numpy as np
import pyperclip
import sounddevice as sd

import audio_devices

# SAPI SpeechVoiceSpeakFlags
_SVSF_ASYNC = 1
_SVSF_PURGE = 2


def get_selected_text(timeout_s=0.6, copy_hotkey="ctrl+c"):
    """Copy the current selection without permanently disturbing the clipboard.

    Clears the clipboard first so an empty result reliably means "nothing was
    selected" rather than "the selection happened to match what was already
    there". The previous contents are restored on a short delay.

    copy_hotkey matters: in terminals Ctrl+C is the interrupt/break signal, not
    copy, so sending it there fails to copy AND can kill a running command.
    Callers pass "ctrl+shift+c" for terminals.
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

    keyboard.send(copy_hotkey)

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
        # SAPI objects are apartment-threaded: one per thread, never shared.
        # A single cached instance reused from another thread marshals across
        # apartments and blocks, which made stop() take seconds instead of ms.
        self._tls = threading.local()
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

    def preload(self):
        """Warm the engine so the first hotkey press isn't slow.

        Loading the Piper model takes ~1.7s; doing it lazily meant the first
        read-aloud of the session stalled before any sound. Call this on a
        background thread at startup instead.
        """
        try:
            if self.engine == "piper":
                self._load_piper()
        except Exception as e:
            self._log(f"tts preload failed: {e}")

    def stop(self):
        """Interrupt playback. Safe from a keyboard hook -- never blocks.

        Note for the Windows engine: we deliberately do NOT touch the SAPI
        object here. It lives in the speaking thread's COM apartment, and
        calling across threads marshals badly -- it blocked instead of purging,
        so playback ran on for seconds after stop(). Setting the flag is enough;
        the speak loop polls it and purges on its own thread within ~50ms.
        """
        self._stop.set()
        if self.engine == "piper":
            try:
                sd.stop()
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

    def _sapi_for_this_thread(self):
        """Get (or create) this thread's own SAPI voice."""
        sapi = getattr(self._tls, "sapi", None)
        if sapi is None:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            sapi = win32com.client.Dispatch("SAPI.SpVoice")
            self._tls.sapi = sapi
        return sapi

    def _speak_windows(self, text):
        sapi = self._sapi_for_this_thread()
        # SAPI rate is -10..10; map speed 1.0 -> 0, 1.2 -> +1, 0.8 -> -1.
        try:
            rate = int(round((float(self.speed) - 1.0) * 5))
            sapi.Rate = max(-10, min(10, rate))
        except Exception:
            pass

        sapi.Speak(text, _SVSF_ASYNC)
        # Short poll interval so a stop request is honoured promptly.
        while not sapi.WaitUntilDone(50):
            if self._stop.is_set():
                # Measured: SAPI's purge blocks ~1s flushing the audio device,
                # but setting Volume to 0 is instantaneous. Mute first so the
                # user hears silence immediately, and report ourselves as no
                # longer speaking before the slow purge, so a quick second
                # press starts a new read instead of being swallowed.
                saved_volume = None
                try:
                    saved_volume = sapi.Volume
                    sapi.Volume = 0
                except Exception:
                    pass
                self._speaking.clear()
                try:
                    sapi.Speak("", _SVSF_PURGE)
                except Exception:
                    pass
                if saved_volume is not None:
                    try:
                        sapi.Volume = saved_volume
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

    def _speak_piper(self, text):
        """Play through ONE continuous output stream.

        An earlier version called sd.play() per sentence, which opened and tore
        down a stream for every chunk. sd.play() also cuts off whatever is
        already playing, and the poll loop could return before a chunk had
        finished -- so sentences were clipped and gapped ("scratched CD").

        Here a single OutputStream pulls from a shared buffer that the
        synthesis thread fills. Piper runs ~20x faster than realtime, so the
        producer stays far ahead and playback is continuous.
        """
        voice = self._load_piper()
        cfg = self._piper_config()
        sample_rate = int(getattr(voice.config, "sample_rate", 22050) or 22050)

        buf = collections.deque()
        buf_lock = threading.Lock()
        produced_all = threading.Event()
        finished = threading.Event()
        counts = {"chunks": 0}

        def produce():
            try:
                gen = voice.synthesize(text, cfg) if cfg else voice.synthesize(text)
                for chunk in gen:
                    if self._stop.is_set():
                        break
                    audio = np.asarray(chunk.audio_float_array, dtype=np.float32)
                    with buf_lock:
                        buf.append(audio)
                    counts["chunks"] += 1
            except Exception as e:
                self._log(f"tts synth error: {e}")
            finally:
                produced_all.set()

        threading.Thread(target=produce, daemon=True).start()

        def callback(outdata, frames, _time_info, _status):
            if self._stop.is_set():
                outdata[:] = 0
                raise sd.CallbackStop
            filled = 0
            with buf_lock:
                while filled < frames and buf:
                    head = buf[0]
                    take = min(len(head), frames - filled)
                    outdata[filled:filled + take, 0] = head[:take]
                    filled += take
                    if take == len(head):
                        buf.popleft()
                    else:
                        buf[0] = head[take:]
            if filled < frames:
                outdata[filled:, 0] = 0.0
                # Only end the stream once synthesis is done AND the buffer has
                # drained -- otherwise a brief producer lag would end playback.
                if produced_all.is_set():
                    raise sd.CallbackStop

        # Small cushion before opening the stream so it never starts on empty.
        deadline = time.time() + 2.0
        while time.time() < deadline and not produced_all.is_set():
            if self._stop.is_set():
                return "stopped before playback"
            with buf_lock:
                buffered = sum(len(a) for a in buf)
            if buffered >= sample_rate * 0.3:
                break
            time.sleep(0.01)

        # Opened under the PortAudio lock and counted, so a device-list refresh
        # never re-initialises PortAudio underneath live playback.
        with audio_devices.PA_LOCK:
            stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                callback=callback,
                finished_callback=finished.set,
            )
            audio_devices.stream_opened()
        try:
            with stream:
                while not finished.is_set():
                    if self._stop.is_set():
                        break
                    time.sleep(0.02)
        finally:
            audio_devices.stream_closed()

        return f"{counts['chunks']} chunks"
