from __future__ import annotations

import unittest

from greaseweazle_gui.read_disk import ReadProgress
from greaseweazle_gui.track_health import (
    TrackCondition,
    build_track_health,
    build_write_health,
)
from greaseweazle_gui.write_disk import WriteProgress


def update(
    cylinder: int,
    head: int,
    read: int,
    total: int,
    *,
    retry: str | None = None,
) -> ReadProgress:
    return ReadProgress(
        0.5,
        cylinder,
        head,
        1,
        160,
        read,
        total,
        retry,
        f"IBM MFM ({read}/{total} sectors)",
    )


class TrackHealthTests(unittest.TestCase):
    def test_classifies_clean_recovered_and_damaged_tracks(self) -> None:
        report = build_track_health(
            (
                update(0, 0, 9, 9),
                update(0, 1, 7, 9),
                update(0, 1, 9, 9, retry="1"),
                update(1, 0, 6, 9, retry="3"),
            )
        )

        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(
            [track.condition for track in report.tracks],
            [
                TrackCondition.GOOD,
                TrackCondition.RECOVERED,
                TrackCondition.DAMAGED,
            ],
        )
        self.assertEqual(report.recovered_count, 1)
        self.assertEqual(report.damaged_count, 1)

    def test_empty_progress_has_no_report(self) -> None:
        self.assertIsNone(build_track_health(()))

    def test_write_retry_is_reported_as_recovered(self) -> None:
        report = build_write_health(
            (
                WriteProgress(0.5, 0, 0, 1, 2, "1", "Retry #1"),
                WriteProgress(0.5, 0, 0, 1, 2, None, "Verified"),
                WriteProgress(1.0, 0, 1, 2, 2, None, "Verified"),
            ),
            succeeded=True,
        )

        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(report.tracks[0].condition, TrackCondition.RECOVERED)
        self.assertEqual(report.tracks[1].condition, TrackCondition.GOOD)


if __name__ == "__main__":
    unittest.main()
