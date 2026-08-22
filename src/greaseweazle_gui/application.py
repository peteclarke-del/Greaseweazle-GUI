"""GTK application lifecycle."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio  # noqa: E402

from .window import MainWindow


class GreaseweazleApplication(Adw.Application):
    """Greaseweazle desktop application."""

    def __init__(self) -> None:
        super().__init__(
            application_id="com.github.pclarke.GreaseweazleGUI",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )

    def do_activate(self) -> None:
        window = self.get_active_window()
        if window is None:
            window = MainWindow(application=self)
            window.present()
            window.begin_device_detection()
        else:
            window.present()

