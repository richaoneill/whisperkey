"""
Mute the default speakers while recording, to stop audio (music, video)
bleeding out of the speakers and back into the microphone.

Uses pycaw over the Windows Core Audio API (pure Python + COM, no native DLL,
so it isn't affected by Smart App Control). All calls are defensive: audio
control must never be able to crash the dictation loop.
"""
from ctypes import cast, POINTER

import comtypes
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume


class OutputMuter:
    def __init__(self):
        self._prev_mute = None  # what the mute state was before we touched it

    def _endpoint(self):
        dev = AudioUtilities.GetSpeakers()
        # Newer pycaw exposes the volume interface directly.
        endpoint = getattr(dev, "EndpointVolume", None)
        if endpoint is not None:
            return endpoint
        # Classic pycaw API fallback.
        interface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))

    def mute(self):
        """Mute output, remembering the prior state."""
        try:
            comtypes.CoInitialize()
            vol = self._endpoint()
            self._prev_mute = vol.GetMute()
            vol.SetMute(1, None)
        except Exception:
            self._prev_mute = None

    def restore(self):
        """Restore output — but only unmute if it wasn't already muted."""
        try:
            comtypes.CoInitialize()
            if self._prev_mute == 0:
                self._endpoint().SetMute(0, None)
        except Exception:
            pass
        finally:
            self._prev_mute = None
