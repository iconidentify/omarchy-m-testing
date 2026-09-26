import sys

from .app import main
from .host import RealHost


def run() -> int:
    try:
        return main(sys.argv[1:], RealHost())
    except KeyboardInterrupt:
        print("\nInterrupted. Nothing was uploaded.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(run())
