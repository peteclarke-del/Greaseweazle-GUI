"""Native GTK view for the bundled user and technical guide."""

from __future__ import annotations

from importlib.resources import files

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk  # noqa: E402

from .help_content import HELP_TOPICS, HelpTopic


class HelpView(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.set_vexpand(True)
        self._topic_list = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.SINGLE,
            activate_on_single_click=True,
            width_request=240,
        )
        self._topic_list.add_css_class("navigation-sidebar")
        self._topic_list.connect("row-selected", self._topic_selected)
        for index, topic in enumerate(HELP_TOPICS):
            row = Gtk.ListBoxRow()
            row.set_child(
                Gtk.Label(
                    label=topic.title,
                    xalign=0,
                    margin_top=10,
                    margin_bottom=10,
                    margin_start=12,
                    margin_end=12,
                )
            )
            row.topic_index = index
            self._topic_list.append(row)
        navigation = Gtk.ScrolledWindow(width_request=240)
        navigation.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        navigation.set_child(self._topic_list)
        self.append(navigation)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        self._article = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=16,
            margin_top=24,
            margin_bottom=32,
            margin_start=32,
            margin_end=32,
        )
        article_scroller = Gtk.ScrolledWindow(hexpand=True)
        article_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        article_scroller.set_child(self._article)
        self.append(article_scroller)
        self._topic_list.select_row(self._topic_list.get_row_at_index(0))

    def _topic_selected(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        self._show_topic(HELP_TOPICS[row.topic_index])

    def _show_topic(self, topic: HelpTopic) -> None:
        while child := self._article.get_first_child():
            self._article.remove(child)
        title = Gtk.Label(label=topic.title, xalign=0, wrap=True)
        title.add_css_class("title-1")
        self._article.append(title)
        summary = Gtk.Label(label=topic.summary, xalign=0, wrap=True)
        summary.add_css_class("dim-label")
        self._article.append(summary)

        image_path = files("greaseweazle_gui").joinpath("help_images", topic.screenshot)
        if image_path.is_file():
            picture = Gtk.Picture.new_for_filename(str(image_path))
            picture.set_tooltip_text(topic.screenshot_alt)
            picture.update_property(
                [Gtk.AccessibleProperty.LABEL], [topic.screenshot_alt]
            )
            picture.set_content_fit(Gtk.ContentFit.CONTAIN)
            picture.set_can_shrink(True)
            picture.set_size_request(-1, 280)
            frame = Gtk.Frame()
            frame.set_child(picture)
            self._article.append(frame)

        for section in topic.sections:
            heading = Gtk.Label(label=section.heading, xalign=0, wrap=True)
            heading.add_css_class("title-3")
            heading.set_margin_top(8)
            self._article.append(heading)
            for paragraph in section.paragraphs:
                self._article.append(
                    Gtk.Label(
                        label=paragraph,
                        xalign=0,
                        wrap=True,
                        selectable=True,
                        max_width_chars=88,
                    )
                )
            if section.steps:
                steps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                for number, text in enumerate(section.steps, start=1):
                    line = Gtk.Box(
                        orientation=Gtk.Orientation.HORIZONTAL,
                        spacing=10,
                    )
                    marker = Gtk.Label(label=str(number), valign=Gtk.Align.START)
                    marker.add_css_class("heading")
                    marker.set_size_request(24, -1)
                    line.append(marker)
                    line.append(
                        Gtk.Label(
                            label=text,
                            xalign=0,
                            wrap=True,
                            hexpand=True,
                            max_width_chars=82,
                        )
                    )
                    steps.append(line)
                self._article.append(steps)
