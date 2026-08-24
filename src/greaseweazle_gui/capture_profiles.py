"""User-facing preservation profiles for physical disk reads."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CaptureProfile:
    name: str
    description: str
    revolutions: int | None = None
    retries: int | None = None
    seek_retries: int | None = None
    preserve_raw: bool = False

    @property
    def read_options(self) -> dict[str, int | None]:
        return {
            "revolutions": self.revolutions,
            "retries": self.retries,
            "seek_retries": self.seek_retries,
        }


CAPTURE_PROFILES = (
    CaptureProfile(
        "Normal",
        "Fast standard read using Greaseweazle defaults.",
    ),
    CaptureProfile(
        "Difficult media",
        "Extra revolutions and seek retries for ageing or unreliable disks.",
        revolutions=2,
        retries=5,
        seek_retries=2,
    ),
    CaptureProfile(
        "Archival",
        "Three revolutions with thorough retries for preservation captures.",
        revolutions=3,
        retries=8,
        seek_retries=2,
    ),
    CaptureProfile(
        "Protected software",
        "Retain multiple revolutions as raw SCP so timing, weak bits, and protection tracks survive.",
        revolutions=5,
        retries=8,
        seek_retries=2,
        preserve_raw=True,
    ),
)
