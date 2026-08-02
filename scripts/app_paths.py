"""Where the tool considers itself to live.

Running from source, that is the repository folder. Running from a packaged
executable it is the folder holding the .exe, which is not the same thing:
PyInstaller unpacks the code into a temporary directory and deletes it on exit,
so anything anchored to __file__ would write output and downloaded tools into a
folder that disappears.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def tool_root() -> Path:
    """The folder the user thinks of as "where the tool is"."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]
