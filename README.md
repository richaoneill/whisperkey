# WhisperKey

Local, offline **voice in and voice out** for Windows. Hold a key to dictate into
any app; tap another to have your selected text read back to you.

A free, private alternative to paid dictation and read-aloud apps. **No cloud, no
account, no subscription.** Audio never leaves your machine.

```
  Dictate    [hold F9]  ->  speak       ->  [release]  ->  text appears where you type
  Read aloud [select text]  ->  [tap F10]  ->  it reads it back  ->  [tap F10] to stop
```

## Features

- **Fully offline** — [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  for speech-to-text and [Piper](https://github.com/rhasspy/piper) for
  text-to-speech, both running locally on CPU. Works on a plane.
- **Read anything aloud** — select text in any app and tap F10. Uses a neural
  voice, not the robotic built-in Windows one. Tap again to stop.
- **Types into any app** — browsers, editors, Office, chat.
- **Terminal-aware** — PowerShell and Windows Terminal often ignore programmatic
  paste, so text is sent there as Unicode keystrokes instead. Everywhere else
  uses clipboard paste, and your previous clipboard is restored.
- **Spoken punctuation** — say "new line", "exclamation point", "open quote"…
  Fully configurable.
- **Mutes your speakers while recording** so music doesn't bleed into the mic.
- **Runs in the tray** — blue mic icon, red while recording. Optional launch at
  login.
- **Self-healing** — a supervisor relaunches the app if it ever crashes.
- **Cheap on CPU** — event-driven hotkey, ~0.05% of a core at idle.

## Requirements

- **Windows 10/11** (uses Windows APIs for injection, tray, and audio)
- **Python 3.9+**
- A microphone

No GPU needed. On a modest laptop CPU (Intel Core 7 150U), a ~5 second phrase
transcribes in roughly **0.7 seconds** with the default `base.en` model.

## Install

```powershell
git clone https://github.com/richaoneill/whisperkey.git
cd whisperkey
powershell -ExecutionPolicy Bypass -File setup.ps1
```

The first launch downloads the Whisper model (~140 MB) once, then it's cached.

## Use

Start it:

```powershell
.\run.bat
```

**Dictate:** hold `F9`, speak, release. A high beep means recording started, a
low beep means it stopped. Text lands in the focused field.

**Read aloud:** select text anywhere, tap `F10`. Tap `F10` again to stop. A low
tone means nothing was selected. Starting a dictation also stops playback.

> **Why a hotkey and not a right-click menu?** Windows has no API for adding an
> item to every application's text context menu — each app draws its own. A
> global hotkey is the only mechanism that genuinely works everywhere, including
> terminals.

### Optional: a better read-aloud voice

Out of the box, read-aloud uses the built-in Windows voices — instant, no
download, but robotic. For a markedly more natural neural voice, opt in to
[Piper](https://github.com/rhasspy/piper):

```powershell
.venv\Scripts\python.exe -m pip install piper-tts
.venv\Scripts\python.exe -m piper.download_voices en_US-lessac-medium --download-dir models
```

Restart the app and it switches automatically. **Note:** `piper-tts` is
GPL-3.0-or-later, while this project is MIT — see the license notes at the
bottom before redistributing a bundle containing it.

### Run automatically in the background

**Recommended — Scheduled Task** (survives crashes *and* full process death,
relaunching within ~10 minutes without needing a login). Run once in an
**administrator** PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File install-task.ps1
```

Add ` -Elevated` to also let it type into elevated/admin windows. Remove it with
`uninstall-task.ps1`.

**Simpler — Startup shortcut** (no admin, but only relaunches at login):

```powershell
powershell -ExecutionPolicy Bypass -File install-startup.ps1
```

Undo with `uninstall-startup.ps1`. To quit either way, right-click the tray mic
icon → **Quit**.

## Configuration — `config/config.json`

| Key | Default | Meaning |
|---|---|---|
| `hotkey` | `f9` | Push-to-talk key. Single keys are event-driven; combos like `ctrl+alt+d` also work. |
| `model_size` | `base.en` | `tiny.en` (fastest) → `small.en` / `medium.en` (more accurate, slower) |
| `compute_type` | `int8` | Quantization. `int8` is the fast CPU default. |
| `device` | `cpu` | Set to `cuda` if you have an NVIDIA GPU. |
| `injection_mode` | `auto` | `auto`, `paste`, or `keystroke` |
| `restore_clipboard` | `true` | Put your previous clipboard back after pasting |
| `mute_audio_while_recording` | `true` | Mute speakers while you speak |
| `beep_feedback` | `true` | Start/stop beeps |
| `min_record_seconds` | `0.3` | Ignore accidental taps shorter than this |
| `voice_commands` | see file | Spoken phrase → text mapping |
| `tts_enabled` | `true` | Read-aloud on/off |
| `tts_hotkey` | `f10` | Tap to read selection, tap again to stop |
| `tts_model` | `models/en_US-lessac-medium.onnx` | Piper voice. [Browse voices](https://huggingface.co/rhasspy/piper-voices) |
| `tts_speed` | `1.0` | `1.2` is faster, `0.9` slower |
| `tts_max_chars` | `20000` | Safety cap on a single read |

Restart the app after editing config.

### Spoken punctuation

Whisper already adds commas and periods from your phrasing. `voice_commands`
handles the symbols it *can't* infer:

| Say | Get |
|---|---|
| "new line" | line break |
| "new paragraph" | blank line |
| "exclamation point" | `!` |
| "question mark" | `?` |
| "open quote" / "close quote" | `"` |
| "open paren" / "close paren" | `(` `)` |

`comma` and `period` are deliberately **not** mapped — they're common words, and
remapping them mangles phrases like "the Jurassic period".

## Troubleshooting

**Nothing gets typed.** A normal-privilege app can't send keys to an elevated
window. Run `run.bat` as administrator to dictate into admin apps.

**Wrong or empty text.** Check `data/whisperkey.log`. If the logged text is
correct but nothing appeared, it's an injection issue; if the text is wrong,
it's a mic issue (the app uses your Windows *default* input device).

**It stopped working.** Check `data/whisperkey.log` for a crash entry and
`data/faulthandler.log` for native crashes. The supervisor should relaunch it
automatically within seconds.

**Accuracy too low.** Set `model_size` to `small.en` and restart.

**`ImportError: DLL load failed ... Application Control policy has blocked this
file`.** Windows Smart App Control blocks PyAV's unsigned bundled DLL.
`src/av_shim.py` already works around this by stubbing PyAV — the app feeds
Whisper raw audio arrays and never decodes files, so nothing is lost.

## How it works

```
Dictate:    F9 hook  -> record (sounddevice) -> faster-whisper (local)
                     -> format (spoken punctuation, spacing, caps)
                     -> inject (clipboard paste, or keystrokes in terminals)

Read aloud: F10 hook -> copy selection (Ctrl+C, clipboard restored after)
                     -> Piper (local) -> play, interruptible
```

| File | Role |
|---|---|
| `src/main.py` | Hotkeys, recording, tray, orchestration |
| `src/postprocess.py` | Spoken punctuation, spacing, capitalization |
| `src/tts.py` | Selection capture and local speech synthesis |
| `src/audio_mute.py` | Mute/restore speakers via Windows Core Audio |
| `src/supervisor.py` | Relaunches the app if it crashes |
| `src/av_shim.py` | PyAV stub for Smart App Control |
| `src/bench_transcribe.py`, `src/bench_audio.py` | Perf/leak benchmarks |

## Privacy

Audio is captured, transcribed in-process, and discarded. Nothing is uploaded
and no audio is written to disk. The app uses a global keyboard hook — required
for a system-wide push-to-talk key — but only to detect the hotkeys and type your
dictated text. **No keystrokes are logged.**

Read-aloud sends `Ctrl+C` to copy whatever you have selected, speaks it locally,
and restores your previous clipboard. The selected text is never written to disk
or transmitted. See [SECURITY.md](SECURITY.md).

## Status

Personal project, shared as-is. It works well for the author's daily use, but
it's not a supported product — issues and pull requests are welcome, though
responses may be slow.

## Contact

Built by **Rich O'Neill** — [LinkedIn](https://www.linkedin.com/in/richardaoneill/)

Questions, bugs, or ideas: open an
[issue](https://github.com/richaoneill/whisperkey/issues). For anything else,
LinkedIn is the best way to reach me.

## License

MIT — see [LICENSE](LICENSE).

### Third-party licenses

This project's own code is MIT. Dependencies keep their own licenses, and are
installed from PyPI rather than bundled:

- **MIT** — faster-whisper, CTranslate2, keyboard, onnxruntime
- **BSD / PSF** — numpy, pyperclip, pywin32
- **Apache-2.0** — tokenizers, huggingface_hub
- **LGPL-3.0** — [pystray](https://github.com/moses-palmer/pystray) (system tray
  icon). Used as an unmodified library installed via pip, so it can be replaced
  or upgraded independently.

The Whisper models are released by OpenAI under MIT; the CTranslate2 conversions
are distributed by SYSTRAN.

#### Piper is optional, and it is GPL

Read-aloud defaults to the **built-in Windows SAPI voices**, which add no extra
license obligations. That is why nothing in `requirements.txt` pulls in Piper.

If you opt in to the neural voice, note that
[piper-tts](https://github.com/rhasspy/piper) is **GPL-3.0-or-later** (it bundles
espeak-ng). Installing it yourself for personal use is fine. But if you
redistribute a bundle that combines this project with Piper, the combined work
falls under GPL-3.0 — you cannot ship that combination as MIT. Keeping Piper an
opt-in install is what keeps this project's own MIT licensing clean.
