"""
WhisperKey - local push-to-talk dictation, running as a background
system-tray app.

Hold the hotkey, speak, release. Audio is transcribed locally with
faster-whisper (no cloud, no cost) and injected into the active field.

Injection is app-aware:
  - Terminals (PowerShell / Windows Terminal / cmd): typed as Unicode
    keystrokes, which paste-blind terminals accept reliably.
  - Everything else: clipboard paste (Ctrl+V), then the clipboard is
    restored so we don't stomp what you had copied.

A microphone icon sits in the system tray (blue = idle, red = recording).
Right-click it to Quit.
"""

import json
import os
import sys
import time
import threading
import traceback
import faulthandler

import av_shim  # noqa: F401  -- stubs PyAV before faster_whisper import

import numpy as np
import sounddevice as sd
import keyboard
import pyperclip
import win32gui
import win32process
import win32api
import win32con
import win32event
import winerror
from faster_whisper import WhisperModel
import pystray
from PIL import Image, ImageDraw

from postprocess import format_text

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "config.json")
LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "whisperkey.log")
MUTEX_NAME = "WhisperKey_SingleInstance_v1"

# Hold a reference so the OS mutex lives for the process lifetime.
_instance_mutex = None


def log(msg):
    """Append a timestamped line to the app log (best-effort)."""
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{stamp} [pid {os.getpid()}] {msg}\n")
    except Exception:
        pass


def acquire_single_instance():
    """Return True if we are the only instance; False if one is already running."""
    global _instance_mutex
    _instance_mutex = win32event.CreateMutex(None, False, MUTEX_NAME)
    return win32api.GetLastError() != winerror.ERROR_ALREADY_EXISTS


def install_crash_logging():
    """Log Python and native crashes so a silent death leaves a trace."""
    # Native (C-level) fatal errors, e.g. a PortAudio segfault.
    try:
        fault_path = os.path.join(os.path.dirname(LOG_PATH), "faulthandler.log")
        os.makedirs(os.path.dirname(fault_path), exist_ok=True)
        # Keep the handle open for the process lifetime.
        global _fault_file
        _fault_file = open(fault_path, "a", encoding="utf-8")
        faulthandler.enable(_fault_file)
    except Exception:
        pass

    def _hook(exc_type, exc_value, exc_tb):
        log("UNCAUGHT: " + "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))

    sys.excepthook = _hook

    def _thread_hook(args):
        log(
            "THREAD CRASH: "
            + "".join(
                traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
            )
        )

    threading.excepthook = _thread_hook


_fault_file = None

IDLE_COLOR = (60, 130, 246, 255)   # blue
REC_COLOR = (220, 40, 40, 255)     # red
SPEAK_COLOR = (34, 197, 94, 255)   # green — reading selection aloud


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def beep(freq, dur_ms, enabled):
    if enabled:
        try:
            win32api.Beep(freq, dur_ms)
        except Exception:
            pass


def foreground_process_name():
    """Return the lowercase exe name of the focused window, or '' on failure."""
    try:
        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, pid
        )
        try:
            exe = win32process.GetModuleFileNameEx(handle, 0)
        finally:
            win32api.CloseHandle(handle)
        return os.path.basename(exe).lower()
    except Exception:
        return ""


def make_icon_image(color):
    """Draw a simple microphone glyph for the tray icon."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([26, 10, 38, 38], radius=6, fill=color)          # mic body
    d.arc([20, 18, 44, 46], start=0, end=180, fill=color, width=4)       # cradle
    d.line([32, 46, 32, 54], fill=color, width=4)                        # stem
    d.line([24, 54, 40, 54], fill=color, width=4)                        # base
    return img


_ICON_CACHE = {}


def get_icon_image(state):
    """Cached icons — these were being redrawn on every keypress.

    state: "idle" (blue), "rec" (red, dictating), "speak" (green, reading aloud)
    """
    if state not in _ICON_CACHE:
        color = {"rec": REC_COLOR, "speak": SPEAK_COLOR}.get(state, IDLE_COLOR)
        _ICON_CACHE[state] = make_icon_image(color)
    return _ICON_CACHE[state]


class Recorder:
    def __init__(self, sample_rate):
        self.sample_rate = sample_rate
        self.frames = []
        self.stream = None
        self.recording = False

    def _callback(self, indata, frames, time_info, status):
        if self.recording:
            self.frames.append(indata.copy())

    def start(self):
        self.frames = []
        self.recording = True
        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self.stream.start()

    def stop(self):
        self.recording = False
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        if not self.frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self.frames, axis=0).flatten()


def inject_text(text, cfg):
    """Insert text into the active field, choosing method by focused app."""
    if not text:
        return

    mode = cfg.get("injection_mode", "auto")
    proc = foreground_process_name()
    is_terminal = proc in [p.lower() for p in cfg.get("terminal_processes", [])]

    use_keystrokes = mode == "keystroke" or (mode == "auto" and is_terminal)

    if use_keystrokes:
        # Types Unicode directly; works in terminals that ignore Ctrl+V.
        keyboard.write(text, delay=0)
        return

    # Clipboard paste path (default for normal fields).
    saved = None
    if cfg.get("restore_clipboard", True):
        try:
            saved = pyperclip.paste()
        except Exception:
            saved = None

    pyperclip.copy(text)
    time.sleep(0.05)
    keyboard.send("ctrl+v")

    if saved is not None:
        def _restore():
            time.sleep(0.4)
            try:
                pyperclip.copy(saved)
            except Exception:
                pass

        threading.Thread(target=_restore, daemon=True).start()


class App:
    def __init__(self, cfg, model):
        self.cfg = cfg
        self.model = model
        self.recorder = Recorder(cfg["sample_rate"])
        self.stop_event = threading.Event()
        # Event-driven hotkey state. Hooks only flip a flag and signal; all real
        # work happens on the worker thread so the keyboard listener is never
        # blocked (blocking it would lag typing system-wide).
        self._want_recording = False
        self._recording_now = False
        self._state_changed = threading.Event()
        self._hooked = False
        self.muter = None
        if cfg.get("mute_audio_while_recording", False):
            try:
                from audio_mute import OutputMuter
                self.muter = OutputMuter()
            except Exception:
                log("could not init audio muter:\n" + traceback.format_exc())
                self.muter = None

        # Text-to-speech (read selection aloud). Optional: if the voice model
        # isn't downloaded, dictation still works and TTS just stays off.
        self.speaker = None
        self._tts_requested = threading.Event()
        if cfg.get("tts_enabled", True):
            try:
                from tts import Speaker

                model = cfg.get("tts_model", "models/en_US-lessac-medium.onnx")
                if not os.path.isabs(model):
                    model = os.path.join(os.path.dirname(__file__), "..", model)
                # Always constructed: without a Piper model it falls back to the
                # built-in Windows voices, so read-aloud works out of the box.
                self.speaker = Speaker(
                    model,
                    cfg.get("tts_speed", 1.0),
                    log,
                    cfg.get("tts_engine", "auto"),
                )
            except Exception:
                log("tts init failed:\n" + traceback.format_exc())
                self.speaker = None

        self.icon = pystray.Icon(
            "whisperkey",
            make_icon_image(IDLE_COLOR),
            "WhisperKey",
            menu=pystray.Menu(
                pystray.MenuItem(lambda i: f"Dictate: {self.cfg['hotkey']}", None, enabled=False),
                pystray.MenuItem(
                    lambda i: (
                        f"Read aloud: {self.cfg.get('tts_hotkey', 'f10')}"
                        f" ({self.speaker.engine})"
                        if self.speaker else "Read aloud: off"
                    ),
                    None,
                    enabled=False,
                ),
                pystray.MenuItem(lambda i: f"Model: {self.cfg['model_size']}", None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self.on_quit),
            ),
        )

    def set_icon_state(self, state):
        self.icon.icon = get_icon_image(state)

    def set_recording_icon(self, recording):
        self.set_icon_state("rec" if recording else "idle")

    def on_quit(self, icon, item):
        self.stop_event.set()
        self._state_changed.set()  # wake the worker so it can exit
        self._tts_requested.set()
        if self.speaker:
            self.speaker.stop()
        self.icon.stop()

    def _on_press(self):
        # Dictating interrupts reading — you can't talk over it anyway, and the
        # speakers are about to be muted.
        if self.speaker and self.speaker.speaking:
            self.speaker.stop()
        # Ding first (so it's audible), then mute output, then start recording.
        beep(880, 80, self.cfg["beep_feedback"])
        if self.muter:
            self.muter.mute()
        self.recorder.start()
        self.set_recording_icon(True)

    def _on_release(self):
        audio = self.recorder.stop()
        self.set_recording_icon(False)
        if self.muter:
            self.muter.restore()
        beep(440, 80, self.cfg["beep_feedback"])

        duration = len(audio) / self.cfg["sample_rate"] if len(audio) else 0
        if duration < self.cfg.get("min_record_seconds", 0.3):
            return

        t0 = time.time()
        segments, _ = self.model.transcribe(
            audio, language="en", beam_size=1, vad_filter=True
        )
        text = "".join(seg.text for seg in segments).strip()
        stt_ms = (time.time() - t0) * 1000
        text = format_text(
            text,
            self.cfg.get("voice_commands"),
            self.cfg.get("smart_formatting", True),
        )
        # Perf trail: lets us spot real-world slowdowns instead of guessing.
        log(f"utterance: {duration:.1f}s audio -> {stt_ms:.0f}ms stt, {len(text)} chars")
        if text:
            inject_text(text, self.cfg)

    def _recover(self):
        """Return to a known-good idle state after an error."""
        try:
            self.recorder.recording = False
            self.set_recording_icon(False)
            if self.muter:
                self.muter.restore()
        except Exception:
            pass

    def install_hooks(self):
        """Event-driven hotkey (single keys only). Returns True if installed.

        Avoids polling, which previously woke 50x/second forever and burned
        hours of CPU. Handlers do nothing but set a flag -- never blocking work.
        """
        key = self.cfg["hotkey"]
        if "+" in key:
            return False  # combos fall back to polling

        def on_press(_e):
            if not self._want_recording:
                self._want_recording = True
                self._state_changed.set()

        def on_release(_e):
            if self._want_recording:
                self._want_recording = False
                self._state_changed.set()

        try:
            keyboard.on_press_key(key, on_press)
            keyboard.on_release_key(key, on_release)
            self._hooked = True
            log(f"hotkey '{key}' installed event-driven (no polling)")
            return True
        except Exception:
            log("hook install failed, falling back to polling:\n" + traceback.format_exc())
            return False

    def install_tts_hook(self):
        """Read-aloud hotkey: tap to read the selection, tap again to stop."""
        if not self.speaker:
            return False
        key = self.cfg.get("tts_hotkey", "f10")
        if "+" in key:
            log(f"tts hotkey '{key}' is a combo; only single keys are supported")
            return False

        def on_tts(_e):
            # Stopping is instant and safe to do from a hook (sets a flag and
            # calls sd.stop). Starting is slow -- clipboard round-trip plus
            # synthesis -- so the worker thread handles that.
            if self.speaker.speaking:
                self.speaker.stop()
            else:
                self._tts_requested.set()

        try:
            keyboard.on_press_key(key, on_tts)
            log(f"tts hotkey '{key}' installed (tap to read, tap again to stop)")
            return True
        except Exception:
            log("tts hook install failed:\n" + traceback.format_exc())
            return False

    def tts_worker(self):
        """Handle read-aloud requests off the keyboard-hook thread."""
        from tts import get_selected_text

        while not self.stop_event.is_set():
            if not self._tts_requested.wait(timeout=0.5):
                continue
            self._tts_requested.clear()
            if self.stop_event.is_set():
                break
            try:
                text = get_selected_text()
                if not text:
                    # Low tone: nothing was selected.
                    beep(300, 120, self.cfg.get("beep_feedback", True))
                    log("tts: nothing selected")
                    continue
                self.set_icon_state("speak")
                self.speaker.speak(text, self.cfg.get("tts_max_chars", 20000))
            except Exception:
                log("tts worker error:\n" + traceback.format_exc())
            finally:
                self.set_icon_state("idle")

    def worker(self):
        """React to hotkey transitions. Blocks when idle, so ~0% CPU at rest."""
        if self._hooked:
            while not self.stop_event.is_set():
                # Blocks (no busy-wait); timeout just re-checks stop_event.
                if not self._state_changed.wait(timeout=0.5):
                    continue
                self._state_changed.clear()
                try:
                    want = self._want_recording
                    if want and not self._recording_now:
                        self._recording_now = True
                        self._on_press()
                    elif not want and self._recording_now:
                        self._recording_now = False
                        self._on_release()
                except Exception:
                    log("worker error:\n" + traceback.format_exc())
                    self._recording_now = False
                    self._recover()
            return

        # Fallback: polling (used for combo hotkeys).
        hotkey = self.cfg["hotkey"]
        was_pressed = False
        while not self.stop_event.is_set():
            try:
                pressed = keyboard.is_pressed(hotkey)
                if pressed and not was_pressed:
                    self._on_press()
                elif not pressed and was_pressed:
                    self._on_release()
                was_pressed = pressed
            except Exception:
                log("worker iteration error:\n" + traceback.format_exc())
                self._recover()
                was_pressed = False
            time.sleep(0.03)

    def run(self):
        self.install_hooks()
        self.install_tts_hook()
        threading.Thread(target=self.worker, daemon=True).start()
        if self.speaker:
            threading.Thread(target=self.tts_worker, daemon=True).start()
        try:
            self.icon.run()  # blocks on the main thread until Quit
        finally:
            self.stop_event.set()
            self._state_changed.set()
            self._tts_requested.set()  # wake the tts worker so it can exit
            if self.speaker:
                self.speaker.stop()
            try:
                keyboard.unhook_all()
            except Exception:
                pass


def main():
    install_crash_logging()

    if not acquire_single_instance():
        log("second instance blocked; exiting")
        print("WhisperKey is already running; exiting.", flush=True)
        return

    cfg = load_config()
    log(f"starting (hotkey={cfg['hotkey']}, model={cfg['model_size']})")
    print(f"Loading model '{cfg['model_size']}'...", flush=True)
    model = WhisperModel(
        cfg["model_size"], device=cfg["device"], compute_type=cfg["compute_type"]
    )
    log("model ready; tray active")
    print("Ready. Tray icon active.", flush=True)
    App(cfg, model).run()
    log("quit")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)
