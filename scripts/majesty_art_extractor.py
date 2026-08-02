"""Entry point for the packaged executable.

Double-clicked, it opens the window. Run with arguments, it behaves as the
command line tool, so a single file covers both.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

# When frozen, the modules sit beside this file inside the bundle; from source
# they are in the same folder either way.
sys.path.insert(0, str(Path(__file__).resolve().parent))


class _NullWriter(io.TextIOBase):
    """Stands in for a missing stdout.

    A windowed build has no console, so sys.stdout and sys.stderr are None and
    the first print() would raise. The window captures output into its own log
    while extracting; this only covers anything printed outside that.
    """

    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        return None


def attach_parent_console() -> bool:
    """Borrow the console that launched us, if there is one.

    A windowed build has no console of its own, so command-line use would print
    into nowhere and the calling shell would return immediately instead of
    waiting. Attaching to the parent gives back both. Double-clicked there is
    no parent console and this simply does nothing.
    """
    try:
        import ctypes

        ATTACH_PARENT_PROCESS = -1
        if not ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
            return False
    except (AttributeError, OSError, ImportError):
        return False

    for name, stream in (("stdout", "CONOUT$"), ("stderr", "CONOUT$"), ("stdin", "CONIN$")):
        mode = "r" if name == "stdin" else "w"
        try:
            setattr(sys, name, open(stream, mode, encoding="utf-8", errors="replace", buffering=1))
        except OSError:
            pass
    return True


def main() -> int:
    if len(sys.argv) > 1:
        attached = attach_parent_console()
        if sys.stdout is None:
            sys.stdout = _NullWriter()
        if sys.stderr is None:
            sys.stderr = _NullWriter()

        import extract_assets

        code = extract_assets.main()
        if attached:
            # The shell prints its prompt as soon as we exit, which would land
            # on the same line as our last output.
            print()
        return code

    if sys.stdout is None:
        sys.stdout = _NullWriter()
    if sys.stderr is None:
        sys.stderr = _NullWriter()

    import extractor_gui

    return extractor_gui.main()


if __name__ == "__main__":
    raise SystemExit(main())
