"""
Stub out PyAV so faster-whisper imports without its bundled ffmpeg DLL.

Windows Smart App Control blocks PyAV's unsigned native DLL. faster-whisper
only needs PyAV to decode audio *files*; we always hand it a numpy array from
the microphone, so decode_audio() never runs. Importing this module before
faster_whisper satisfies the `import av` at load time without the real DLL.

If file decoding is ever attempted, the stub raises a clear error instead of
silently misbehaving.
"""
import sys
import types


def install():
    if "av" in sys.modules:
        return

    av = types.ModuleType("av")

    error = types.ModuleType("av.error")

    class InvalidDataError(Exception):
        pass

    error.InvalidDataError = InvalidDataError
    av.error = error

    def _missing(name):
        raise RuntimeError(
            "PyAV is stubbed (blocked by Windows Smart App Control). "
            "Audio-file decoding is unavailable; feed numpy arrays instead."
        )

    av.__getattr__ = _missing  # PEP 562 module-level __getattr__

    sys.modules["av"] = av
    sys.modules["av.error"] = error


install()
