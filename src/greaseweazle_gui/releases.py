"""Reading the repository's latest GitHub release and downloading its files.

The repository is public, so the release and its files are read without
signing in, and every request names the application in its User-Agent. A
request that fails raises UpdateError with the reason as a sentence, so a
check that could not be made is never read as "up to date". Nothing here runs
until the user presses Check for Application Updates.
"""

from __future__ import annotations

import http.client
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .branding import APPLICATION_NAME, HOMEPAGE

USER_AGENT = f"{APPLICATION_NAME}/{__version__} (+{HOMEPAGE})"
GITHUB_JSON = {"Accept": "application/vnd.github+json"}
DOCUMENT_LIMIT = 1024 * 1024
CHUNK_SIZE = 64 * 1024

Progress = Callable[[int, int | None], None]
# urllib.request.urlopen, or a stand-in with the same signature in the tests.
Opener = Callable[..., Any]


class UpdateError(RuntimeError):
    """The update could not be checked or installed; the message is for the user."""


class UpdateCancelled(UpdateError):
    """The user cancelled the update."""


@dataclass(frozen=True, slots=True)
class Reply:
    """The status and body of a reply, whatever the status."""

    status: int
    data: bytes = b""


def host(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc or url


def _cancelled(cancel: threading.Event | None) -> bool:
    return cancel is not None and cancel.is_set()


def _open(
    url: str, headers: dict[str, str], timeout: float, opener: Opener | None
) -> Any:
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise UpdateError(f"{url} is not a web address.")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    return (opener or urllib.request.urlopen)(request, timeout=timeout)


def _unreachable(url: str, error: BaseException) -> UpdateError:
    reason = getattr(error, "reason", None) or error
    return UpdateError(f"{host(url)} could not be reached: {reason}.")


def _not_saved(target: Path, error: OSError) -> UpdateError:
    reason = error.strerror or error
    return UpdateError(f"The download could not be saved in {target.parent}: {reason}.")


def refusal(url: str, status: int) -> UpdateError:
    """The reason, as a sentence, for a reply other than 200."""
    name = host(url)
    if status in (403, 429):
        return UpdateError(
            f"{name} refused the request (HTTP {status}). GitHub does this when too many "
            "requests come from one address; try again later."
        )
    if status >= 500:
        return UpdateError(
            f"{name} is having problems; try again later (HTTP {status})."
        )
    return UpdateError(f"{name} sent an unexpected reply (HTTP {status}).")


def get_reply(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_bytes: int = DOCUMENT_LIMIT,
    timeout: float = 20.0,
    opener: Opener | None = None,
) -> Reply:
    """Fetch a small document, returning the reply whatever its status.

    Raises UpdateError when the server cannot be reached or the reply is
    larger than ``max_bytes``.
    """
    try:
        with _open(url, headers or {}, timeout, opener) as response:
            data = response.read(max_bytes + 1)
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as error:
        error.close()
        return Reply(error.code)
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise _unreachable(url, error) from error
    if len(data) > max_bytes:
        raise UpdateError(f"The reply from {host(url)} was larger than expected.")
    return Reply(status, data)


def get_bytes(url: str, **options: Any) -> bytes:
    """The body of a small document; any status but 200 raises UpdateError."""
    reply = get_reply(url, **options)
    if reply.status != 200:
        raise refusal(url, reply.status)
    return reply.data


def download(
    url: str,
    target: Path,
    *,
    progress: Progress | None = None,
    cancel: threading.Event | None = None,
    timeout: float = 60.0,
    opener: Opener | None = None,
) -> Path:
    """Download ``url`` to ``target`` through ``target.part`` and return ``target``.

    Raises UpdateCancelled when ``cancel`` is set, and UpdateError with the
    reason when the download fails. Nothing is left at ``target.part``.
    """
    partial = target.with_name(target.name + ".part")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = partial.open("wb")
    except OSError as error:
        raise _not_saved(target, error) from error
    try:
        with handle, _open(url, {}, timeout, opener) as response:
            length = response.headers.get("Content-Length", "")
            total = int(length) if length.isdigit() else None
            done = 0
            while True:
                if _cancelled(cancel):
                    raise UpdateCancelled("The update was cancelled.")
                if progress is not None:
                    progress(done, total)
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                try:
                    handle.write(chunk)
                except OSError as error:
                    raise _not_saved(target, error) from error
                done += len(chunk)
        if total is not None and done != total:
            raise UpdateError(
                f"The connection to {host(url)} closed after {done} of {total} bytes; "
                "try again."
            )
    except urllib.error.HTTPError as error:
        error.close()
        partial.unlink(missing_ok=True)
        raise refusal(url, error.code) from error
    except UpdateError:
        partial.unlink(missing_ok=True)
        raise
    except (OSError, ValueError, http.client.HTTPException) as error:
        partial.unlink(missing_ok=True)
        raise _unreachable(url, error) from error
    try:
        partial.replace(target)
    except OSError as error:
        partial.unlink(missing_ok=True)
        raise _not_saved(target, error) from error
    return target


def latest_release(url: str, *, opener: Opener | None = None) -> dict[str, Any] | None:
    """The release GitHub marks as the latest, or None when none is published.

    GitHub never marks a draft or a prerelease as the latest release.
    """
    reply = get_reply(url, headers=GITHUB_JSON, opener=opener)
    if reply.status == 404:
        return None
    if reply.status != 200:
        raise refusal(url, reply.status)
    try:
        release = json.loads(reply.data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise UpdateError(f"The reply from {host(url)} could not be read.") from error
    if not isinstance(release, dict) or "tag_name" not in release:
        message = release.get("message") if isinstance(release, dict) else None
        reason = f"{host(url)} did not send a release"
        raise UpdateError(f"{reason}: {message}." if message else f"{reason}.")
    return release
