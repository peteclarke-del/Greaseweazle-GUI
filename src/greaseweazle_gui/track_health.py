"""Summarise physical read quality by cylinder and head."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .read_disk import ReadProgress
from .write_disk import WriteProgress


class TrackCondition(Enum):
    GOOD = "good"
    RECOVERED = "recovered"
    DAMAGED = "damaged"


@dataclass(frozen=True, slots=True)
class TrackHealth:
    cylinder: int
    head: int
    condition: TrackCondition
    sectors_read: int | None
    sectors_total: int | None
    attempts: int
    message: str


@dataclass(frozen=True, slots=True)
class TrackHealthReport:
    tracks: tuple[TrackHealth, ...]

    @property
    def recovered_count(self) -> int:
        return sum(track.condition is TrackCondition.RECOVERED for track in self.tracks)

    @property
    def damaged_count(self) -> int:
        return sum(track.condition is TrackCondition.DAMAGED for track in self.tracks)

    @property
    def summary(self) -> str:
        if self.damaged_count:
            return f"{self.damaged_count} damaged track side(s)"
        if self.recovered_count:
            return f"All tracks read; {self.recovered_count} required retries"
        return f"All {len(self.tracks)} track sides read cleanly"


def build_track_health(
    updates: tuple[ReadProgress, ...],
) -> TrackHealthReport | None:
    if not updates:
        return None
    grouped: dict[tuple[int, int], list[ReadProgress]] = {}
    for update in updates:
        grouped.setdefault((update.cylinder, update.head), []).append(update)

    tracks: list[TrackHealth] = []
    for (cylinder, head), attempts in sorted(grouped.items()):
        final = attempts[-1]
        incomplete = (
            final.sectors_read is not None
            and final.sectors_total is not None
            and final.sectors_read < final.sectors_total
        ) or "Giving up" in final.message
        retried = len(attempts) > 1 or any(item.retry for item in attempts)
        condition = (
            TrackCondition.DAMAGED
            if incomplete
            else TrackCondition.RECOVERED
            if retried
            else TrackCondition.GOOD
        )
        tracks.append(
            TrackHealth(
                cylinder,
                head,
                condition,
                final.sectors_read,
                final.sectors_total,
                len(attempts),
                final.message,
            )
        )
    return TrackHealthReport(tuple(tracks))


def build_write_health(
    updates: tuple[WriteProgress, ...], succeeded: bool
) -> TrackHealthReport | None:
    if not updates:
        return None
    grouped: dict[tuple[int, int], list[WriteProgress]] = {}
    for update in updates:
        grouped.setdefault((update.cylinder, update.head), []).append(update)
    final_key = (updates[-1].cylinder, updates[-1].head)
    tracks: list[TrackHealth] = []
    for (cylinder, head), attempts in sorted(grouped.items()):
        final = attempts[-1]
        retried = len(attempts) > 1 or any(item.retry for item in attempts)
        failed = not succeeded and (cylinder, head) == final_key
        condition = (
            TrackCondition.DAMAGED
            if failed
            else TrackCondition.RECOVERED
            if retried
            else TrackCondition.GOOD
        )
        tracks.append(
            TrackHealth(
                cylinder,
                head,
                condition,
                None,
                None,
                len(attempts),
                final.message,
            )
        )
    return TrackHealthReport(tuple(tracks))
