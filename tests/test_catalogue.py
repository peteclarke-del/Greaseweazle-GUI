import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from greaseweazle_gui import image_sources
from greaseweazle_gui.catalogue import scan_catalogue
from greaseweazle_gui.disk_formats import DISK_FORMATS
from greaseweazle_gui.image_detection import ImageFormatGuess
from greaseweazle_gui.image_inspector import ImageInspection, inspect_image


class CatalogueTests(unittest.TestCase):
    def test_duplicate_hashes_are_counted_and_other_files_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            folder = Path(folder_name)
            first = folder / "one.st"
            second = folder / "two.st"
            first.write_bytes(b"same")
            second.write_bytes(b"same")
            (folder / "notes.txt").write_text("ignore")

            def inspect(path: Path) -> ImageInspection:
                return ImageInspection(
                    path,
                    4,
                    "a" * 64,
                    ImageFormatGuess(None, "unknown", "unknown"),
                    None,
                    None,
                    "readable",
                )

            with patch("greaseweazle_gui.catalogue.inspect_image", inspect):
                entries = scan_catalogue(folder)
        self.assertEqual(len(entries), 2)
        self.assertEqual({entry.duplicate_count for entry in entries}, {2})

    def test_hfe_images_are_included(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            image = Path(folder_name) / "disk.hfe"
            image.write_bytes(b"hfe")
            inspection = ImageInspection(
                image,
                3,
                "b" * 64,
                ImageFormatGuess(None, "unknown", "unknown"),
                None,
                None,
                "readable",
            )
            with patch(
                "greaseweazle_gui.catalogue.inspect_image", return_value=inspection
            ):
                entries = scan_catalogue(Path(folder_name))

        self.assertEqual(tuple(entry.path.name for entry in entries), ("disk.hfe",))


AMIGA_DD = b"DOS\x00" + bytes(80 * 2 * 11 * 512 - 4)


class ZippedCatalogueTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        catalog = patch(
            "greaseweazle_gui.image_detection.supported_formats",
            return_value=DISK_FORMATS,
        )
        catalog.start()
        self.addCleanup(catalog.stop)

    def make_zip(self, name: str, members: dict[str, bytes]) -> Path:
        archive = self.folder / name
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for member, data in members.items():
                bundle.writestr(member, data)
        return archive

    def test_zipped_image_is_catalogued_and_matches_its_loose_copy(self) -> None:
        archive = self.make_zip(
            "game.zip", {"Game/disk1.adf": AMIGA_DD, "Game/readme.txt": b"text"}
        )
        (self.folder / "disk1.adf").write_bytes(AMIGA_DD)

        entries = scan_catalogue(self.folder)

        zipped = next(entry for entry in entries if entry.member)
        loose = next(entry for entry in entries if not entry.member)
        self.assertEqual(len(entries), 2)
        self.assertEqual(zipped.path, archive)
        self.assertEqual(zipped.member, "Game/disk1.adf")
        self.assertEqual(zipped.name, "disk1.adf")
        self.assertEqual(zipped.location, f"{archive} › Game/disk1.adf")
        self.assertEqual(zipped.size, len(AMIGA_DD))
        self.assertEqual(zipped.format_label, loose.format_label)
        self.assertEqual(zipped.sha256, loose.sha256)
        self.assertEqual({entry.duplicate_count for entry in entries}, {2})

    def test_only_image_members_are_decompressed(self) -> None:
        self.make_zip(
            "game.zip",
            {
                "disk1.adf": AMIGA_DD,
                "disk2.adf": AMIGA_DD[:-1] + b"\x01",
                "manual.pdf": b"pdf",
                "cover.jpg": b"jpeg",
            },
        )
        unpacked: list[str] = []
        real_unpack = image_sources._unpack

        def spy(bundle: zipfile.ZipFile, member: str, destination: Path) -> Path:
            unpacked.append(member)
            return real_unpack(bundle, member, destination)

        with patch.object(image_sources, "_unpack", spy):
            entries = scan_catalogue(self.folder)

        self.assertEqual(unpacked, ["disk1.adf", "disk2.adf"])
        self.assertEqual([entry.member for entry in entries], unpacked)

    def test_zip_without_images_adds_nothing(self) -> None:
        self.make_zip("docs.zip", {"MANUAL.BIN": b"not listed by name"})

        self.assertEqual(scan_catalogue(self.folder), ())

    def test_unreadable_zips_are_reported_without_counting_as_duplicates(
        self,
    ) -> None:
        for name in ("one.zip", "two.zip"):
            (self.folder / name).write_bytes(b"PK\x03\x04" + bytes(64))

        entries = scan_catalogue(self.folder)

        self.assertEqual(len(entries), 2)
        for entry in entries:
            self.assertEqual(entry.sha256, "")
            self.assertEqual(entry.duplicate_count, 1)
            self.assertIn("could not be read", entry.problem or "")

    def test_member_that_cannot_be_unpacked_is_reported_by_name(self) -> None:
        self.make_zip("game.zip", {"disk1.adf": AMIGA_DD})

        with patch.object(image_sources, "MAX_UNPACKED_BYTES", 1024):
            (entry,) = scan_catalogue(self.folder)

        self.assertEqual(entry.member, "disk1.adf")
        self.assertIn("larger than", entry.problem or "")

    def test_limit_stops_inside_a_large_archive(self) -> None:
        self.make_zip("many.zip", {f"disk{index}.adf": AMIGA_DD for index in range(6)})
        inspected: list[Path] = []

        def counting_inspect(path: Path) -> ImageInspection:
            inspected.append(path)
            return inspect_image(path)

        with (
            patch("greaseweazle_gui.catalogue.inspect_image", counting_inspect),
            self.assertRaisesRegex(OSError, "safety limit"),
        ):
            scan_catalogue(self.folder, limit=2)
        self.assertEqual(len(inspected), 3)


if __name__ == "__main__":
    unittest.main()
