"""Locate FFmpeg, and fetch it on request.

Cinematics are the one thing this tool cannot do with the standard library.
The game stores them as Bink video, a proprietary codec with no pure-Python
decoder, so everything else here runs with nothing installed and cinematics are
opt-in.

Nothing is ever downloaded without being asked for. The extractor looks for an
FFmpeg that is already present, and only offers to fetch one when the caller
has explicitly opted into cinematics and confirms the prompt.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
from pathlib import Path
from typing import Callable, Iterable

TOOL_ROOT = Path(__file__).resolve().parents[1]
FFMPEG_DIR = TOOL_ROOT / "tools" / "ffmpeg"
FFMPEG_EXE = FFMPEG_DIR / "ffmpeg.exe"

# gyan.dev is the build the FFmpeg project itself points Windows users to. The
# archive is served over HTTPS and published with a companion .sha256, which is
# downloaded first and used to verify the zip before anything is unpacked or
# run. That is the same trust model as fetching it by hand, made explicit.
FFMPEG_HOME = "https://www.gyan.dev/ffmpeg/builds/"
FFMPEG_URL = FFMPEG_HOME + "ffmpeg-release-essentials.zip"
FFMPEG_SHA_URL = FFMPEG_URL + ".sha256"
FFMPEG_APPROX_MB = 30


class FFmpegUnavailable(RuntimeError):
    """Raised when cinematics were asked for but FFmpeg could not be provided."""


def find_ffmpeg() -> Path | None:
    """Return an FFmpeg already on this machine, or None.

    Checked in order: the copy this tool downloaded, an explicit override, and
    anything on PATH. A user who already has FFmpeg never needs a download.
    """
    if FFMPEG_EXE.is_file():
        return FFMPEG_EXE

    override = os.environ.get("MAJESTY_FFMPEG")
    if override:
        candidate = Path(override)
        if candidate.is_file():
            return candidate

    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def describe_download() -> str:
    return (
        f"Cinematics need FFmpeg, which is not part of this tool.\n\n"
        f"It would be downloaded from:\n  {FFMPEG_URL}\n\n"
        f"About {FFMPEG_APPROX_MB} MB, verified against the publisher's SHA-256, "
        f"and unpacked to:\n  {FFMPEG_DIR}\n\n"
        f"Nothing else on your machine is touched, and you can delete that "
        f"folder at any time.\n\n"
        f"Download it now?"
    )


def download_ffmpeg(progress: Callable[[str], None] | None = None) -> Path:
    """Fetch, verify and unpack FFmpeg. Returns the executable path."""
    # Imported here so the module stays importable on a machine with no network
    # stack configured, and so the import cost is not paid by every run.
    from urllib.request import urlopen

    def say(message: str) -> None:
        if progress:
            progress(message)

    FFMPEG_DIR.mkdir(parents=True, exist_ok=True)
    archive = FFMPEG_DIR / "ffmpeg-download.zip"

    say(f"Fetching checksum from {FFMPEG_SHA_URL}")
    with urlopen(FFMPEG_SHA_URL, timeout=60) as response:  # noqa: S310 -- pinned HTTPS host
        expected = response.read().decode("ascii", "ignore").split()[0].strip().lower()
    if len(expected) != 64:
        raise FFmpegUnavailable(f"Publisher checksum looked wrong: {expected!r}")

    say(f"Downloading FFmpeg (about {FFMPEG_APPROX_MB} MB)")
    digest = hashlib.sha256()
    with urlopen(FFMPEG_URL, timeout=300) as response, archive.open("wb") as handle:  # noqa: S310
        while True:
            block = response.read(1 << 16)
            if not block:
                break
            digest.update(block)
            handle.write(block)

    actual = digest.hexdigest().lower()
    if actual != expected:
        archive.unlink(missing_ok=True)
        raise FFmpegUnavailable(
            "The download did not match the publisher's checksum, so it was discarded.\n"
            f"  expected {expected}\n  got      {actual}"
        )
    say("Checksum verified")

    say("Unpacking")
    extracted = _extract_ffmpeg(archive)
    archive.unlink(missing_ok=True)
    if extracted is None:
        raise FFmpegUnavailable("The archive did not contain ffmpeg.exe")
    say(f"FFmpeg ready at {extracted}")
    return extracted


def _extract_ffmpeg(archive: Path) -> Path | None:
    """Pull just ffmpeg.exe out of the archive, ignoring its folder layout."""
    with zipfile.ZipFile(archive) as bundle:
        member = next(
            (
                name
                for name in bundle.namelist()
                if Path(name).name.lower() == "ffmpeg.exe" and not name.endswith("/")
            ),
            None,
        )
        if member is None:
            return None
        # Read and write explicitly rather than extract(), so nothing in the
        # archive can choose its own path on disk.
        with bundle.open(member) as source, FFMPEG_EXE.open("wb") as target:
            shutil.copyfileobj(source, target)
    return FFMPEG_EXE


def resolve_ffmpeg(
    *,
    allow_download: bool = False,
    confirm: Callable[[str], bool] | None = None,
    progress: Callable[[str], None] | None = None,
) -> Path | None:
    """Find FFmpeg, optionally offering to download it.

    Returns None when cinematics should simply be skipped. Only raises when a
    download was agreed to and then failed.
    """
    existing = find_ffmpeg()
    if existing is not None:
        return existing
    if not allow_download:
        return None
    if confirm is not None and not confirm(describe_download()):
        return None
    return download_ffmpeg(progress)


def skip_notice() -> Iterable[str]:
    return (
        "Cinematics were skipped: FFmpeg is not available.",
        "  They are the only part of the game this tool cannot read on its own.",
        "  Install FFmpeg, put it on PATH, set MAJESTY_FFMPEG to its location,",
        "  or re-run with --cinematics to be offered a download.",
    )
