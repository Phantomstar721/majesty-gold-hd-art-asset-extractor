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
import subprocess
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, NamedTuple, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from app_paths import user_data_root

FFMPEG_DIR = user_data_root() / "ffmpeg"
FFMPEG_EXE = FFMPEG_DIR / "ffmpeg.exe"

class DownloadSource(NamedTuple):
    name: str
    url: str
    checksum_url: str
    checksum_filename: str
    approximate_mb: int


# FFmpeg's own download page recommends both of these Windows build providers.
# GitHub's release CDN is dramatically faster in observed use, so BtbN is the
# primary.  Its shared GPL build is smaller than the static build and includes
# libx264, which the cinematic exporter uses.  Gyan remains a static fallback.
BTBN_HOME = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
BTBN_ARCHIVE_NAME = "ffmpeg-n9.0-latest-win64-gpl-shared-9.0.zip"
BTBN_SOURCE = DownloadSource(
    "GitHub / BtbN",
    BTBN_HOME + BTBN_ARCHIVE_NAME,
    BTBN_HOME + "checksums.sha256",
    BTBN_ARCHIVE_NAME,
    75,
)
GYAN_HOME = "https://www.gyan.dev/ffmpeg/builds/"
GYAN_ARCHIVE_NAME = "ffmpeg-release-essentials.zip"
GYAN_SOURCE = DownloadSource(
    "gyan.dev",
    GYAN_HOME + GYAN_ARCHIVE_NAME,
    GYAN_HOME + GYAN_ARCHIVE_NAME + ".sha256",
    GYAN_ARCHIVE_NAME,
    110,
)
DOWNLOAD_SOURCES = (BTBN_SOURCE, GYAN_SOURCE)

# Public aliases retained for the prompt, CLI documentation, and callers that
# display the chosen primary source.
FFMPEG_URL = BTBN_SOURCE.url
FFMPEG_SHA_URL = BTBN_SOURCE.checksum_url
FFMPEG_APPROX_MB = BTBN_SOURCE.approximate_mb


class FFmpegUnavailable(RuntimeError):
    """Raised when cinematics were asked for but FFmpeg could not be provided."""


def run(command: Sequence[str]) -> subprocess.CompletedProcess:
    """Run FFmpeg without a console window appearing.

    A packaged build is a GUI application with no console of its own, so every
    child process Windows starts gets a fresh one. An extraction launches
    FFmpeg around forty times, once per Bink record plus once per cinematic,
    which showed up as a stream of command prompts flashing over the window.

    CREATE_NO_WINDOW suppresses that. STARTF_USESHOWWINDOW is set as well, for
    the console builds where the flag alone is not enough.
    """
    keywords: dict[str, object] = {}
    if os.name == "nt":
        keywords["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        keywords["startupinfo"] = startup
    return subprocess.run(list(command), capture_output=True, check=False, **keywords)


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
        f"Cinematics and quest maps are Bink video and need FFmpeg, "
        f"which is not part of this tool.\n\n"
        f"It would be downloaded from GitHub's release CDN:\n  {FFMPEG_URL}\n\n"
        f"About {FFMPEG_APPROX_MB} MB, verified against the publisher's SHA-256, "
        f"and unpacked to:\n  {FFMPEG_DIR}\n\n"
        f"If GitHub is unavailable, {GYAN_SOURCE.name} is tried automatically.\n\n"
        f"Nothing else on your machine is touched, and you can delete that "
        f"folder at any time.\n\n"
        f"Download it now?"
    )


def download_ffmpeg(progress: Callable[[str], None] | None = None) -> Path:
    """Fetch, verify and unpack FFmpeg. Returns the executable path."""
    def say(message: str) -> None:
        if progress:
            progress(message)

    try:
        FFMPEG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise FFmpegUnavailable(
            "The FFmpeg folder could not be created.\n\n"
            f"{FFMPEG_DIR}\n\n{error}"
        ) from error
    failures: list[str] = []
    for index, source in enumerate(DOWNLOAD_SOURCES):
        try:
            return _download_from_source(source, say)
        except FFmpegUnavailable as error:
            failures.append(f"{source.name}: {error}")
            if index + 1 < len(DOWNLOAD_SOURCES):
                say(f"{source.name} failed; trying {DOWNLOAD_SOURCES[index + 1].name}")
    raise FFmpegUnavailable(
        "FFmpeg could not be downloaded from any provider.\n\n" + "\n\n".join(failures)
    )


def _download_from_source(source: DownloadSource, say: Callable[[str], None]) -> Path:
    archive = FFMPEG_DIR / "ffmpeg-download.zip"

    try:
        say(f"Fetching {source.name} checksum")
        with urlopen(source.checksum_url, timeout=60) as response:  # noqa: S310 -- fixed HTTPS providers
            checksum_text = response.read().decode("ascii", "ignore")
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise FFmpegUnavailable(_download_error_message(source, "checksum", error)) from error
    expected = _checksum_for(checksum_text, source.checksum_filename)
    if len(expected) != 64:
        raise FFmpegUnavailable(
            f"The checksum manifest did not contain {source.checksum_filename}."
        )

    say(f"Downloading FFmpeg from {source.name} (about {source.approximate_mb} MB)")
    digest = hashlib.sha256()
    downloaded = 0
    next_report = 5 << 20
    try:
        with urlopen(source.url, timeout=300) as response, archive.open("wb") as handle:  # noqa: S310
            try:
                total = int(response.headers.get("Content-Length", "0"))
            except (TypeError, ValueError):
                total = 0
            while True:
                block = response.read(1 << 16)
                if not block:
                    break
                digest.update(block)
                handle.write(block)
                downloaded += len(block)
                if downloaded >= next_report:
                    amount = f"Downloaded {downloaded / (1 << 20):.0f} MB"
                    if total > 0:
                        amount += f" of {total / (1 << 20):.0f} MB"
                    say(amount)
                    next_report += 5 << 20
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        archive.unlink(missing_ok=True)
        raise FFmpegUnavailable(_download_error_message(source, "archive", error)) from error

    actual = digest.hexdigest().lower()
    if actual != expected:
        archive.unlink(missing_ok=True)
        raise FFmpegUnavailable(
            "The download did not match the publisher's checksum, so it was discarded.\n"
            f"  expected {expected}\n  got      {actual}"
        )
    say("Checksum verified")

    say("Unpacking")
    try:
        extracted = _extract_ffmpeg(archive)
    except (OSError, zipfile.BadZipFile) as error:
        raise FFmpegUnavailable(f"The verified FFmpeg archive could not be unpacked.\n\n{error}") from error
    finally:
        archive.unlink(missing_ok=True)
    if extracted is None:
        raise FFmpegUnavailable("The archive did not contain ffmpeg.exe")
    say(f"FFmpeg ready at {extracted}")
    return extracted


def _checksum_for(text: str, filename: str) -> str:
    """Read either a one-line checksum or a multi-file SHA-256 manifest."""
    for line in text.splitlines():
        fields = line.strip().split(maxsplit=1)
        if not fields:
            continue
        digest = fields[0].lower()
        if len(fields) == 1:
            return digest
        listed_name = fields[1].lstrip("* ").replace("\\", "/")
        if PurePosixPath(listed_name).name.lower() == filename.lower():
            return digest
    return ""


def _download_error_message(
    source: DownloadSource, part: str, error: BaseException
) -> str:
    return (
        f"Could not download the FFmpeg {part} from {source.name}.\n\n"
        f"{source.url}\n\n"
        f"{error}\n\n"
        "Check the internet connection and try again. You can also download "
        "a static Windows FFmpeg build manually and place ffmpeg.exe here:\n"
        f"{FFMPEG_EXE}"
    )


def _extract_ffmpeg(archive: Path) -> Path | None:
    """Install ffmpeg.exe and any sibling DLLs, ignoring archive layout."""
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
        binary_dir = PurePosixPath(member).parent
        dll_members = [
            name
            for name in bundle.namelist()
            if PurePosixPath(name).parent == binary_dir
            and PurePosixPath(name).suffix.lower() == ".dll"
        ]
        # DLLs are committed first and ffmpeg.exe last.  An interrupted shared
        # install therefore cannot look complete to find_ffmpeg(); the next run
        # safely overwrites any partial DLL set.  We write by basename rather
        # than extract(), so archive paths never select a destination.
        for name in [*dll_members, member]:
            destination = FFMPEG_DIR / PurePosixPath(name).name
            partial = destination.with_name(destination.name + ".part")
            try:
                with bundle.open(name) as source_file, partial.open("wb") as target:
                    shutil.copyfileobj(source_file, target)
                partial.replace(destination)
            finally:
                partial.unlink(missing_ok=True)
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
        "Cinematics and quest maps were skipped: FFmpeg is not available.",
        "  Those two are Bink video, the only part of the game this tool cannot",
        "  read on its own. Everything else was extracted normally.",
        "  Install FFmpeg, put it on PATH, set MAJESTY_FFMPEG to its location,",
        "  or re-run with --cinematics to be offered a download.",
    )
