import unittest
from pathlib import Path

from greaseweazle_gui import __version__
from greaseweazle_gui.branding import APPLICATION_NAME, APPLICATION_SUBTITLE

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class BrandingTests(unittest.TestCase):
    def test_runtime_version_matches_project_metadata(self) -> None:
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f'version = "{__version__}"', pyproject)

    def test_about_dialog_uses_runtime_version_and_project_links(self) -> None:
        window = (PROJECT_ROOT / "src/greaseweazle_gui/window.py").read_text()

        self.assertIn("version=__version__", window)
        self.assertIn("license_type=Gtk.License.GPL_3_0", window)
        self.assertIn("peteclarke-del/Greaseweazle-GUI", window)

    def test_product_identity_is_exact(self) -> None:
        self.assertEqual(APPLICATION_NAME, "Greaseweazle-GUI")
        self.assertEqual(APPLICATION_SUBTITLE, "for linux")

    def test_desktop_metadata_uses_product_identity(self) -> None:
        desktop = (
            PROJECT_ROOT / "data/com.github.pclarke.GreaseweazleGUI.desktop"
        ).read_text(encoding="utf-8")
        metadata = (
            PROJECT_ROOT / "data/com.github.pclarke.GreaseweazleGUI.metainfo.xml"
        ).read_text(encoding="utf-8")
        self.assertIn(f"Name={APPLICATION_NAME}\n", desktop)
        self.assertIn(f"GenericName={APPLICATION_SUBTITLE}\n", desktop)
        self.assertIn("Exec=greaseweazle-gui\n", desktop)
        self.assertIn(f"<name>{APPLICATION_NAME}</name>", metadata)
        self.assertIn(f"<summary>{APPLICATION_SUBTITLE}</summary>", metadata)

    def test_help_uses_official_greaseweazle_spelling(self) -> None:
        help_text = (PROJECT_ROOT / "src/greaseweazle_gui/help_content.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("Greaseweazle", help_text)
        self.assertNotIn("GreaseWeazle", help_text)
        self.assertNotIn("GreaseWeasel", help_text)


if __name__ == "__main__":
    unittest.main()
