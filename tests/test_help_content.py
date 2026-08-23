from importlib.resources import files
import unittest

from greaseweazle_gui.help_content import HELP_TOPICS


class HelpContentTests(unittest.TestCase):
    def test_topics_have_unique_names_and_real_screenshots(self) -> None:
        self.assertGreaterEqual(len(HELP_TOPICS), 12)
        self.assertEqual(
            len({topic.slug for topic in HELP_TOPICS}), len(HELP_TOPICS)
        )
        image_folder = files("greaseweazle_gui").joinpath("help_images")
        for topic in HELP_TOPICS:
            with self.subTest(topic=topic.slug):
                self.assertTrue(image_folder.joinpath(topic.screenshot).is_file())
                self.assertTrue(topic.sections)

    def test_help_copy_has_no_em_dash(self) -> None:
        pieces = []
        for topic in HELP_TOPICS:
            pieces.extend((topic.title, topic.summary, topic.screenshot_alt))
            for section in topic.sections:
                pieces.append(section.heading)
                pieces.extend(section.paragraphs)
                pieces.extend(section.steps)
        self.assertNotIn("\N{EM DASH}", "\n".join(pieces))

    def test_every_major_operation_is_covered(self) -> None:
        slugs = {topic.slug for topic in HELP_TOPICS}
        self.assertTrue(
            {
                "read",
                "extract",
                "browser",
                "write",
                "blank",
                "image-tools",
                "health",
                "library",
                "maintenance",
                "troubleshooting",
            }.issubset(slugs)
        )


if __name__ == "__main__":
    unittest.main()
