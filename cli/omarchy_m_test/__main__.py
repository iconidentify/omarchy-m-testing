import signal
import sys

from .app import main
from .host import RealHost


def _interrupt(signum, frame):
    # Closing the terminal (SIGHUP) or being asked to stop (SIGTERM) ends the
    # run like Ctrl-C does, so every change is put back and the checkpoint kept.
    raise KeyboardInterrupt


def run() -> int:
    for signum in (signal.SIGHUP, signal.SIGTERM):
        signal.signal(signum, _interrupt)
    try:
        return main(sys.argv[1:], RealHost())
    except KeyboardInterrupt:
        try:
            print("\nInterrupted. Nothing was uploaded.", file=sys.stderr)
        except OSError:
            pass  # the terminal is gone
        return 130


if __name__ == "__main__":
    sys.exit(run())
