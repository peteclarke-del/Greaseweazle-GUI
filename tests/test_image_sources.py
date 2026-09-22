from __future__ import annotations

import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from greaseweazle_gui import catalogue, image_sources
from greaseweazle_gui.disk_formats import DISK_FORMATS
from greaseweazle_gui.image_detection import detect_image_format
from greaseweazle_gui.image_sources import (
    IMAGE_SUFFIXES,
    ZipSourceError,
    extract_zipped_image,
    is_zip_archive,
    unpack_each_zipped_image,
    zipped_images,
)

AMIGA_DD = b"DOS\x00" + bytes(80 * 2 * 11 * 512 - 4)
SOURCE = Path(__file__).resolve().parents[1] / "src" / "greaseweazle_gui"


class ImageSourcesTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.destination = self.folder / "unpacked"
        self.destination.mkdir()

    def make_zip(self, members: dict[str, bytes], name: str = "disks.zip") -> Path:
        archive = self.folder / name
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for member, data in members.items():
                bundle.writestr(member, data)
        return archive

    def test_zip_is_recognised_by_content_whatever_its_name(self) -> None:
        archive = self.make_zip({"game.adf": AMIGA_DD}, name="game.adf")

        self.assertTrue(is_zip_archive(archive))

    def test_disk_image_holding_a_zip_near_its_end_is_not_an_archive(self) -> None:
        inner = self.make_zip({"readme.txt": b"hello"}, name="inner.zip")
        image = self.folder / "disk.adf"
        image.write_bytes(AMIGA_DD[: -inner.stat().st_size] + inner.read_bytes())

        self.assertTrue(zipfile.is_zipfile(image))
        self.assertFalse(is_zip_archive(image))

    def test_missing_file_is_not_an_archive(self) -> None:
        self.assertFalse(is_zip_archive(self.folder / "absent.zip"))

    def test_only_recognised_images_are_offered_in_name_order(self) -> None:
        archive = self.make_zip(
            {
                "Game/Disk2.ADF": b"2",
                "Game/disk1.adf": b"1",
                "Game/readme.txt": b"text",
                "Game/cover.jpg": b"jpeg",
                "__MACOSX/Game/._disk1.adf": b"fork",
                "Game/.hidden.adf": b"hidden",
            }
        )

        self.assertEqual(zipped_images(archive), ("Game/disk1.adf", "Game/Disk2.ADF"))

    def test_single_file_with_an_unknown_name_is_offered_for_content_checks(
        self,
    ) -> None:
        archive = self.make_zip({"MYSTERY.BIN": AMIGA_DD})

        self.assertEqual(zipped_images(archive), ("MYSTERY.BIN",))

    def test_archive_without_a_disk_image_is_refused(self) -> None:
        archive = self.make_zip({"readme.txt": b"a", "notes.txt": b"b"})

        with self.assertRaisesRegex(ZipSourceError, "recognised disk image"):
            zipped_images(archive)

    def test_corrupt_archive_is_refused(self) -> None:
        archive = self.folder / "broken.zip"
        archive.write_bytes(b"PK\x03\x04" + bytes(64))

        with self.assertRaisesRegex(ZipSourceError, "could not be read"):
            zipped_images(archive)

    def test_unpacked_image_is_detected_as_if_chosen_directly(self) -> None:
        archive = self.make_zip({"Workbench/wb13.adf": AMIGA_DD})

        image = extract_zipped_image(
            archive, zipped_images(archive)[0], self.destination
        )

        self.assertEqual(image, self.destination / "wb13.adf")
        self.assertEqual(image.read_bytes(), AMIGA_DD)
        with patch(
            "greaseweazle_gui.image_detection.supported_formats",
            return_value=DISK_FORMATS,
        ):
            guess = detect_image_format(image)
        self.assertEqual(guess.method, "content")
        assert guess.disk_format is not None
        self.assertEqual(guess.disk_format.gw_format, "amiga.amigados")

    def test_member_path_cannot_escape_the_destination(self) -> None:
        archive = self.make_zip({"../../escape.adf": b"data"})

        image = extract_zipped_image(archive, "../../escape.adf", self.destination)

        self.assertEqual(image, self.destination / "escape.adf")
        self.assertFalse((self.folder / "escape.adf").exists())

    def test_oversized_member_is_refused_and_removed(self) -> None:
        archive = self.make_zip({"huge.adf": bytes(4096)})

        with (
            patch.object(image_sources, "MAX_UNPACKED_BYTES", 1024),
            self.assertRaisesRegex(ZipSourceError, "larger than"),
        ):
            extract_zipped_image(archive, "huge.adf", self.destination)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_password_protected_member_is_explained(self) -> None:
        archive = self.make_zip({"secret.adf": b"data"})

        with (
            patch.object(
                zipfile.ZipFile,
                "open",
                side_effect=RuntimeError("File is encrypted, password required"),
            ),
            self.assertRaisesRegex(ZipSourceError, "password-protected"),
        ):
            extract_zipped_image(archive, "secret.adf", self.destination)

    def test_bulk_unpacking_keeps_one_image_on_disk_at_a_time(self) -> None:
        archive = self.make_zip(
            {"b.adf": b"second", "a.adf": b"first", "notes.txt": b"skip"}
        )
        seen = []

        for member, unpacked in unpack_each_zipped_image(archive, self.destination):
            assert isinstance(unpacked, Path)
            seen.append((member, unpacked.read_bytes()))
            self.assertEqual(list(self.destination.iterdir()), [unpacked])

        self.assertEqual(seen, [("a.adf", b"first"), ("b.adf", b"second")])
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_bulk_unpacking_opens_the_archive_once(self) -> None:
        archive = self.make_zip({"a.adf": b"1", "b.adf": b"2", "c.adf": b"3"})
        real_zip = zipfile.ZipFile

        with patch.object(
            image_sources.zipfile, "ZipFile", side_effect=real_zip
        ) as opened:
            members = [
                member
                for member, _ in unpack_each_zipped_image(archive, self.destination)
            ]

        self.assertEqual(members, ["a.adf", "b.adf", "c.adf"])
        self.assertEqual(opened.call_count, 1)

    def test_bulk_unpacking_offers_only_recognised_names(self) -> None:
        archive = self.make_zip({"MYSTERY.BIN": AMIGA_DD})

        self.assertEqual(list(unpack_each_zipped_image(archive, self.destination)), [])

    def test_bulk_unpacking_reports_a_bad_member_and_continues(self) -> None:
        archive = self.make_zip({"a.adf": bytes(4096), "b.adf": b"small"})

        with patch.object(image_sources, "MAX_UNPACKED_BYTES", 1024):
            results = list(unpack_each_zipped_image(archive, self.destination))

        self.assertIsInstance(results[0][1], ZipSourceError)
        self.assertEqual(results[1][0], "b.adf")
        self.assertIsInstance(results[1][1], Path)

    def test_catalogue_scans_the_shared_suffix_list(self) -> None:
        self.assertIs(catalogue.IMAGE_SUFFIXES, IMAGE_SUFFIXES)

    def test_window_does_not_keep_its_own_image_suffix_list(self) -> None:
        """File choosers take their suffixes from image_sources.

        The inspect and write choosers once carried separate copies of the same
        list as the catalogue, so a new format had to be added in three places.
        """
        window = (SOURCE / "window.py").read_text(encoding="utf-8")

        self.assertEqual(re.findall(r'"\*\.[a-z0-9]+"', window), [])

    def test_every_source_image_chooser_unpacks_zips(self) -> None:
        window = (SOURCE / "window.py").read_text(encoding="utf-8")

        for handler in (
            "_on_inspection_image_selected",
            "_on_comparison_image",
            "_on_existing_image_selected",
            "_on_write_image_selected",
        ):
            with self.subTest(handler=handler):
                body = window.split(f"def {handler}(", 1)[1].split("\n    def ", 1)[0]
                self.assertIn("self._with_source_image(", body)


if __name__ == "__main__":
    unittest.main()
