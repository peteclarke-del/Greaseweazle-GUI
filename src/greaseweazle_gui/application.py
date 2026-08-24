"""GTK application lifecycle."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib  # noqa: E402

from .branding import APPLICATION_NAME
from .window import MainWindow


class GreaseweazleApplication(Adw.Application):
    """Greaseweazle-GUI desktop application."""

    def __init__(self) -> None:
        GLib.set_application_name(APPLICATION_NAME)
        super().__init__(
            application_id="com.github.pclarke.GreaseweazleGUI",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.set_accels_for_action("win.help", ["F1"])

    def do_activate(self) -> None:
        window = self.get_active_window()
        if window is None:
            window = MainWindow(application=self)
            window.present()
            documentation_state = os.environ.get("GREASEWEAZLE_GUI_DOCUMENTATION_STATE")
            if documentation_state:
                window.show_documentation_state(documentation_state)
            else:
                window.begin_device_detection()
        else:
            window.present()
