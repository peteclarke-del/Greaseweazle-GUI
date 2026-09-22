"""Recognise disk-image sources, including disk images delivered inside a zip.

Every place that asks the user for a source image (open, inspect, compare, and
write) takes its suffixes from here, and every zipped source is unpacked here,
so the rules for what counts as an image stay in one place.

A zipped source is unpacked to a private directory and then handled exactly as
if the user had chosen the unpacked file. The archive itself is never modified.
"""

from __future__ import annotations

import zipfile
import zlib
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

IMAGE_SUFFIXES = frozenset(
    {
        ".adf",
        ".st",
        ".scp",
        ".a2r",
        ".img",
        ".ima",
        ".ssd",
        ".dsd",
        ".adm",
        ".ads",
        ".adl",
        ".do",
        ".po",
        ".d64",
        ".d71",
        ".d81",
        ".d1m",
        ".d2m",
        ".d4m",
        ".sf7",
        ".hfe",
    }
)
ARCHIVE_SUFFIXES = frozenset({".zip"})

#: The largest image unpacked from an archive. A multi-revolution SCP capture of
#: a high-density disk is well under this; anything larger is not a floppy image
#: and is refused rather than allowed to fill the disk.
MAX_UNPACKED_BYTES = 256 * 1024 * 1024

_LOCAL_FILE_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06")


class ZipSourceError(Exception):
    """A zipped source could not provide a disk image."""


def is_zip_archive(path: Path) -> bool:
    """Return whether *path* is a zip archive, judged by content, not name.

    The archive must begin with a zip record as well as carry a valid central
    directory. A raw disk image can contain a zip file near its end, which
    satisfies the central-directory check alone, so a start-of-file record is
    also required before an image is treated as an archive.
    """
    try:
        with path.open("rb") as source:
            if source.read(4) not in _LOCAL_FILE_SIGNATURES:
                return False
    except OSError:
        return False
    return zipfile.is_zipfile(path)


def _is_ignorable(name: str) -> bool:
    parts = PurePosixPath(name.replace("\\", "/")).parts
    return any(part == "__MACOSX" or part.startswith(".") for part in parts)


def _image_members(
    bundle: zipfile.ZipFile, *, recognised_only: bool
) -> tuple[str, ...]:
    """Choose the disk-image members from the archive's directory alone."""
    files = [
        info.filename
        for info in bundle.infolist()
        if not info.is_dir() and not _is_ignorable(info.filename)
    ]
    images = [
        name for name in files if PurePosixPath(name).suffix.lower() in IMAGE_SUFFIXES
    ]
    if not images and len(files) == 1 and not recognised_only:
        images = files
    return tuple(sorted(images, key=str.casefold))


def zipped_images(archive: Path) -> tuple[str, ...]:
    """Return the members of *archive* that should be offered as disk images.

    Members with a recognised image suffix are offered. When there are none,
    an archive holding exactly one file offers that file, so a misnamed image
    is still inspected by content. Folders, macOS resource forks and hidden
    files are never offered.
    """
    try:
        with zipfile.ZipFile(archive) as bundle:
            images = _image_members(bundle, recognised_only=False)
    except (OSError, zipfile.BadZipFile) as error:
        raise ZipSourceError(f"The zip archive could not be read: {error}") from error
    if not images:
        raise ZipSourceError(
            "The zip archive does not contain a recognised disk image."
        )
    return images


def _unpack(bundle: zipfile.ZipFile, member: str, destination: Path) -> Path:
    """Stream one member of an open archive into *destination*.

    Only the member's own filename is kept, so a member named with ``..`` or an
    absolute path cannot be written outside *destination*. The size is enforced
    while unpacking, not trusted from the archive's own directory.
    """
    name = PurePosixPath(member.replace("\\", "/")).name or "image"
    target = destination / name
    try:
        with bundle.open(member) as source, target.open("wb") as output:
            written = 0
            while chunk := source.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UNPACKED_BYTES:
                    raise ZipSourceError(
                        f"{name} is larger than "
                        f"{MAX_UNPACKED_BYTES // (1024 * 1024)} MB when unpacked "
                        "and is not a floppy disk image."
                    )
                output.write(chunk)
    except ZipSourceError:
        target.unlink(missing_ok=True)
        raise
    except RuntimeError as error:
        # zipfile reports an encrypted member as a RuntimeError.
        target.unlink(missing_ok=True)
        raise ZipSourceError(
            f"{name} is password-protected. Unpack it with an archive tool first."
        ) from error
    except (
        OSError,
        KeyError,
        NotImplementedError,
        zipfile.BadZipFile,
        zlib.error,
    ) as error:
        target.unlink(missing_ok=True)
        raise ZipSourceError(f"{name} could not be unpacked: {error}") from error
    return target


def extract_zipped_image(archive: Path, member: str, destination: Path) -> Path:
    """Unpack one *member* of *archive* into *destination* and return its path."""
    try:
        with zipfile.ZipFile(archive) as bundle:
            return _unpack(bundle, member, destination)
    except (OSError, zipfile.BadZipFile) as error:
        raise ZipSourceError(f"The zip archive could not be read: {error}") from error


def unpack_each_zipped_image(
    archive: Path, destination: Path
) -> Iterator[tuple[str, Path | ZipSourceError]]:
    """Unpack the disk images in *archive* one at a time, for bulk inspection.

    Members are chosen from the archive's directory, so readme files, artwork
    and other non-image members are never decompressed, and only recognised
    image suffixes are considered. The archive is opened once. Each image is
    yielded with its unpacked path, or with the error that stopped it, and its
    file is deleted as soon as the caller asks for the next, so a large archive
    never occupies more than one image's worth of scratch space.
    """
    try:
        bundle = zipfile.ZipFile(archive)
    except (OSError, zipfile.BadZipFile) as error:
        raise ZipSourceError(f"The zip archive could not be read: {error}") from error
    with bundle:
        for member in _image_members(bundle, recognised_only=True):
            try:
                image = _unpack(bundle, member, destination)
            except ZipSourceError as error:
                yield member, error
                continue
            try:
                yield member, image
            finally:
                image.unlink(missing_ok=True)
