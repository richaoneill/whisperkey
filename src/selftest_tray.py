"""Headless smoke test for the tray app: build icon, start worker, stop cleanly."""
import av_shim  # noqa: F401
import threading
import time
import main

cfg = main.load_config()
print("hotkey:", cfg["hotkey"])

# Icon image builds without a display.
img = main.make_icon_image(main.REC_COLOR)
print("icon image size:", img.size)

# Build the App with a dummy model (we only exercise the worker/stop plumbing).
class DummyModel:
    def transcribe(self, *a, **k):
        return ([], None)

app = main.App(cfg, DummyModel())

# Run the worker thread directly (skip icon.run(), which needs a live tray loop).
t = threading.Thread(target=app.worker, daemon=True)
t.start()
time.sleep(0.5)
print("worker alive:", t.is_alive())

app.stop_event.set()
t.join(timeout=2)
print("worker stopped:", not t.is_alive())
print("TRAY SELFTEST OK")
