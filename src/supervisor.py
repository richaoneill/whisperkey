"""
Supervisor: keep WhisperKey alive.

Launches main.py and relaunches it if it dies unexpectedly (e.g. a native
PortAudio crash that no Python try/except can catch). A clean Quit from the
tray menu (exit code 0) stops the supervisor so "Quit" really quits.

Exponential backoff prevents a tight crash-loop; a run that lasted a while
resets the backoff.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(HERE, "main.py")
LOG_PATH = os.path.join(HERE, "..", "data", "whisperkey.log")


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{stamp} [supervisor] {msg}\n")
    except Exception:
        pass


def main():
    backoff = 2
    log("supervisor started")
    while True:
        started = time.time()
        try:
            code = subprocess.run([sys.executable, MAIN]).returncode
        except Exception as e:
            log(f"failed to launch main.py: {e}")
            code = -1

        ran_for = time.time() - started

        if code == 0:
            log("main exited cleanly (0); supervisor stopping")
            break

        if ran_for > 60:
            backoff = 2  # it was stable for a while; reset backoff

        log(f"main crashed (exit {code}) after {ran_for:.0f}s; restarting in {backoff}s")
        time.sleep(backoff)
        backoff = min(backoff * 2, 30)


if __name__ == "__main__":
    main()
