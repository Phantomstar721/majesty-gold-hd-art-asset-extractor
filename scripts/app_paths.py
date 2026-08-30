"""Where the tool considers itself to live.

Running from source, that is the repository folder. Running from a packaged
executable it is the folder holding the .exe, which is not the same thing:
PyInstaller unpacks the code into a temporary directory and deletes it on exit,
so anything anchored to __file__ would write output and downloaded tools into a
folder that disappears.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_DATA_FOLDER = "Majesty Gold HD Art Extractor"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def tool_root() -> Path:
    """The folder the user thinks of as "where the tool is"."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def user_data_root() -> Path:
    """A stable, per-user folder for files the program downloads.

    A subscribed Workshop folder is managed by Steam and may be read-only or
    replaced during an update.  A PyInstaller one-file bundle also runs from a
    disposable ``_MEI`` directory.  Neither is an appropriate home for FFmpeg.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_DATA_FOLDER
    return Path.home() / f".{APP_DATA_FOLDER.lower().replace(' ', '-')}"
