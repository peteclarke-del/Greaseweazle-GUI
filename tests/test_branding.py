from pathlib import Path
import unittest

from greaseweazle_gui.branding import APPLICATION_NAME, APPLICATION_SUBTITLE


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class BrandingTests(unittest.TestCase):
    def test_product_identity_is_exact(self) -> None:
        self.assertEqual(APPLICATION_NAME, "GreaseWeazleGUI")
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
        self.assertIn(f"<name>{APPLICATION_NAME}</name>", metadata)
        self.assertIn(f"<summary>{APPLICATION_SUBTITLE}</summary>", metadata)


if __name__ == "__main__":
    unittest.main()
