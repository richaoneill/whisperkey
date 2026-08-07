# Security

WhisperKey installs a **global keyboard hook** and can **type into any focused
window**. That's the same capability class malware uses, so here's exactly what
it does and doesn't do.

## What the app does

- Registers a system-wide hook so the push-to-talk key works in any application
  (`src/main.py`, `install_hooks`). The handler reads **only** whether the
  configured hotkey went down or up.
- Records the microphone **only while the hotkey is held**.
- Transcribes audio **in-process, on your machine**, using faster-whisper.
- Types the transcribed text into the focused window, either by clipboard paste
  or by simulated Unicode keystrokes.
- For read-aloud, sends `Ctrl+C` to copy the current selection, synthesizes it
  locally, plays it, and restores your previous clipboard contents. The selected
  text stays in memory only.

## What the app does not do

- **No keystroke logging.** Key events other than the hotkeys are never
  inspected, stored, or transmitted.
- **No clipboard monitoring.** The clipboard is touched only in direct response
  to a hotkey press, and its prior contents are restored.
- **No network calls at runtime.** The only download is the Whisper model, from
  Hugging Face, on first launch. After that it runs fully offline.
- **No audio written to disk.** Audio lives in memory and is discarded after
  transcription.
- **No telemetry, analytics, or accounts.**

## What is written to disk

- `data/whisperkey.log` — timestamps, app lifecycle events, and per-utterance
  performance (audio length, transcription time, character count). It records
  the **length** of transcribed text, not the text itself.
- `data/faulthandler.log` — crash stack traces, if a native crash occurs.

Both stay on your machine and are excluded from version control.

## Dependencies

Runtime dependencies are pinned in `requirements.txt`. Before release they were
checked with `pip-audit` (no known vulnerabilities) and scanned with Windows
Defender.

Note that `src/av_shim.py` intentionally stubs out PyAV. This is a workaround
for Windows Smart App Control blocking PyAV's unsigned bundled DLL — it is a
*loading* block, not a malware detection. The stub is safe because the app
feeds Whisper raw audio arrays and never decodes media files.

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

Contact **Rich O'Neill** via
[LinkedIn](https://www.linkedin.com/in/richardaoneill/).

This is a personal project provided as-is, so there is no guaranteed response
time, but security reports will be prioritized over other issues.
