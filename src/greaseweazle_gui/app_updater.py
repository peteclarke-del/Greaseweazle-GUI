"""Checking for, downloading and installing a newer Greaseweazle-GUI from the About window.

The main window keeps one ``AppUpdater``, so an update in progress carries on
when the About window is closed, shows again when it is reopened, and cannot
be started twice. Nothing is checked until the user presses Check for
Application Updates; a check that fails says why and never says "newest".
An update is not installed, and the application does not restart, while a
disk operation is running.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import __version__, app_update  # noqa: E402
from .app_update import AppRelease, PackageTarget  # noqa: E402
from .branding import APPLICATION_NAME  # noqa: E402
from .releases import Progress, UpdateCancelled  # noqa: E402

CHECK_LABEL = "_Check for Application Updates"
BUSY_WHILE_RUNNING = (
    f"{APPLICATION_NAME} can be updated once the disk operation has finished"
)
RESTART_WHILE_RUNNING = (
    f"{APPLICATION_NAME} can restart once the disk operation has finished"
)


class UpdateHost(Protocol):
    """What the updater needs from the main window."""

    def operation_running(self) -> bool: ...

    def restart(self) -> bool: ...

    def app_update_installed(self, release: AppRelease) -> None: ...

    def record_diagnostic(self, title: str, detail: str) -> None: ...


class UpdateService:
    """The work behind the update, which the interface tests replace."""

    def target(self) -> PackageTarget | None:
        return app_update.installed_target()

    def check(self) -> AppRelease | None:
        return app_update.check(self.target())

    def download(
        self, release: AppRelease, progress: Progress, cancel: threading.Event
    ) -> Path:
        return app_update.download(release, progress, cancel)

    def install(self, package: Path) -> None:
        app_update.install(package)


@dataclass(frozen=True, slots=True)
class AppUpdateState:
    # "idle", "checking", "current", "available", "downloading", "installing",
    # "installed" or "failed"
    phase: str
    message: str = ""
    fraction: float | None = None
    release: AppRelease | None = None

    @property
    def busy(self) -> bool:
        return self.phase in ("checking", "downloading", "installing")


def on_main(function: Callable[..., Any], *args: Any) -> None:
    """Call ``function(*args)`` once on the GTK main loop."""

    def call() -> bool:
        function(*args)
        return GLib.SOURCE_REMOVE

    GLib.idle_add(call)


def in_thread(
    work: Callable[[], Any],
    done: Callable[[Any], None],
    failed: Callable[[BaseException], None],
    name: str,
) -> None:
    """Run ``work`` on a daemon thread and deliver its outcome on the main loop."""

    def worker() -> None:
        try:
            result = work()
        except Exception as error:  # noqa: BLE001 - reported to the user
            on_main(failed, error)
            return
        on_main(done, result)

    threading.Thread(target=worker, name=name, daemon=True).start()


def download_text(done: int, total: int | None) -> str:
    if total:
        return f"Downloading {min(100, done * 100 // total)}%"
    return f"Downloading {GLib.format_size(done)}"


class AppUpdater:
    """The application update, shared by the About window and the main window."""

    def __init__(self, host: UpdateHost, service: UpdateService | None = None) -> None:
        self._host = host
        self.service = service or UpdateService()
        self.state = AppUpdateState("idle")
        self._listeners: list[Callable[[AppUpdateState], None]] = []
        self._cancel: threading.Event | None = None

    def subscribe(self, listener: Callable[[AppUpdateState], None]) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[AppUpdateState], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _set(self, state: AppUpdateState) -> None:
        self.state = state
        for listener in list(self._listeners):
            listener(state)

    def available_text(self, release: AppRelease) -> str:
        text = f"{release.name} is available. You have version {__version__}."
        if release.installable:
            return text
        target = self.service.target()
        if target is None:
            return (
                f"{text} This copy was not installed from a release package, so it "
                "cannot update itself: update the source, or install the package from "
                "the release page."
            )
        return (
            f"{text} The release has no package for {target.system}; "
            "the release page lists the packages it has."
        )

    def show_result(self, release: AppRelease | None) -> None:
        """Show what a check found: a newer release, or None for the newest."""
        if release is None:
            newest = f"{APPLICATION_NAME} {__version__} is the newest version"
            self._set(AppUpdateState("current", newest))
            return
        self._set(
            AppUpdateState("available", self.available_text(release), release=release)
        )

    def check(self) -> None:
        if self.state.busy:
            return
        self._set(AppUpdateState("checking", "Asking GitHub for the newest version"))

        def failed(error: BaseException) -> None:
            message = f"Could not check for a newer version: {error}"
            self._host.record_diagnostic("Check for Application Updates", message)
            self._set(AppUpdateState("failed", message))

        in_thread(self.service.check, self.show_result, failed, "app-update-check")

    def install(self, release: AppRelease) -> None:
        if self.state.busy:
            return
        if self._host.operation_running():
            # The package replaces the gw that the operation is running.
            self._set(AppUpdateState("available", BUSY_WHILE_RUNNING, release=release))
            return
        cancel = threading.Event()
        self._cancel = cancel
        self._set(
            AppUpdateState("downloading", "Downloading the package", 0.0, release)
        )

        def progress(done: int, total: int | None) -> None:
            on_main(shown, done, total)

        def shown(done: int, total: int | None) -> None:
            if self.state.phase == "downloading" and self.state.release is release:
                fraction = done / total if total else None
                text = download_text(done, total)
                self._set(AppUpdateState("downloading", text, fraction, release))

        def downloaded(package: Path) -> None:
            self._cancel = None
            message = f"Installing {release.name}. The system asks for your password."
            self._set(AppUpdateState("installing", message, None, release))
            in_thread(
                lambda: self.service.install(package),
                lambda _result: installed(),
                failed,
                "app-update-install",
            )

        def installed() -> None:
            message = (
                f"{release.name} is installed. Restart {APPLICATION_NAME} to use it."
            )
            self._set(AppUpdateState("installed", message, release=release))
            self._host.app_update_installed(release)

        def failed(error: BaseException) -> None:
            self._cancel = None
            if isinstance(error, UpdateCancelled) or cancel.is_set():
                text = str(error) if isinstance(error, UpdateCancelled) else ""
                message = text or "The update was cancelled."
                self._set(AppUpdateState("available", message, release=release))
                return
            message = f"The update failed: {error}"
            self._host.record_diagnostic("Check for Application Updates", message)
            self._set(AppUpdateState("failed", message, release=release))

        in_thread(
            lambda: self.service.download(release, progress, cancel),
            downloaded,
            failed,
            "app-update-download",
        )

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.set()

    def restart(self) -> None:
        """Restart into the installed version, or say why it cannot yet."""
        if not self._host.restart():
            self._set(replace(self.state, message=RESTART_WHILE_RUNNING))


class AppUpdateControls(Gtk.Box):
    """The About window's button, status line and progress for the application update."""

    def __init__(self, updater: AppUpdater) -> None:
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
            halign=Gtk.Align.CENTER,
            margin_top=6,
        )
        self.add_css_class("app-update")
        self._updater = updater
        self.button = Gtk.Button(use_underline=True, halign=Gtk.Align.CENTER)
        self.button.add_css_class("pill")
        self.button.connect("clicked", self._on_button)
        self.append(self.button)
        progress_line = Gtk.Box(spacing=6)
        self.progress = Gtk.ProgressBar(hexpand=True, valign=Gtk.Align.CENTER)
        self.progress.set_size_request(220, -1)
        progress_line.append(self.progress)
        self.cancel_button = Gtk.Button(label="_Cancel", use_underline=True)
        self.cancel_button.connect("clicked", lambda _button: updater.cancel())
        progress_line.append(self.cancel_button)
        self.progress_line = progress_line
        self.append(progress_line)
        self.spinner = Gtk.Spinner(halign=Gtk.Align.CENTER)
        self.append(self.spinner)
        self.status = Gtk.Label(
            wrap=True,
            justify=Gtk.Justification.CENTER,
            max_width_chars=44,
            selectable=True,
        )
        self.status.add_css_class("dim-label")
        self.append(self.status)
        self.page_button = Gtk.Button(
            label="Release _Page", use_underline=True, halign=Gtk.Align.CENTER
        )
        self.page_button.add_css_class("flat")
        self.page_button.connect("clicked", self._on_page)
        self.append(self.page_button)
        updater.subscribe(self.show)
        self.show(updater.state)

    def detach(self) -> None:
        """Stop following the updater, when the About window closes."""
        self._updater.unsubscribe(self.show)

    def show(self, state: AppUpdateState) -> None:
        release = state.release
        self.status.set_text(state.message)
        self.status.set_visible(bool(state.message))
        self.progress_line.set_visible(state.phase == "downloading")
        if state.phase == "downloading":
            if state.fraction is None:
                self.progress.pulse()
            else:
                self.progress.set_fraction(state.fraction)
        installing = state.phase == "installing"
        self.spinner.set_visible(installing)
        if installing:
            self.spinner.start()
        else:
            self.spinner.stop()
        self.button.set_visible(state.phase not in ("downloading", "installing"))
        self.button.set_sensitive(not state.busy)
        suggested = state.phase in ("available", "installed") and bool(
            release is not None and (release.installable or state.phase == "installed")
        )
        if suggested:
            self.button.add_css_class("suggested-action")
        else:
            self.button.remove_css_class("suggested-action")
        self.page_button.set_visible(
            release is not None
            and bool(release.page_url)
            and state.phase != "installed"
        )
        if state.phase == "checking":
            self.button.set_label("Checking")
        elif state.phase == "available" and release is not None:
            if release.installable:
                self.button.set_label(f"_Update to {release.version}")
            else:
                self.button.set_label("Open Release _Page")
                self.page_button.set_visible(False)
        elif state.phase == "installed":
            self.button.set_label(f"_Restart {APPLICATION_NAME}")
        else:
            self.button.set_label(CHECK_LABEL)

    def _on_button(self, _button: Gtk.Button) -> None:
        state = self._updater.state
        release = state.release
        if state.phase == "installed":
            self._updater.restart()
        elif state.phase == "available" and release is not None:
            if release.installable:
                self.confirm(release)
            else:
                self._on_page()
        else:
            self._updater.check()

    def _on_page(self, *_args: object) -> None:
        release = self._updater.state.release
        if release is not None and release.page_url:
            open_uri(release.page_url)

    def confirm(self, release: AppRelease) -> Adw.MessageDialog:
        """Ask before downloading and installing ``release``."""
        target = self._updater.service.target()
        system = target.system if target else "this system"
        size = (
            f" ({GLib.format_size(release.package_size)})"
            if release.package_size
            else ""
        )
        body = (
            f"Version {release.version} is available; you have {__version__}. The "
            f"package for {system}{size} is downloaded from GitHub, checked against "
            "the release's checksums and installed, which asks for your password. "
            "Your disk images and capture reports are not changed."
        )
        if release.notes:
            body += f"\n\n{release.notes}"
        root = self.get_root()
        dialog = Adw.MessageDialog.new(
            root if isinstance(root, Gtk.Window) else None,
            f"Update {APPLICATION_NAME}?",
            body,
        )
        dialog.add_response("cancel", "_Cancel")
        dialog.add_response("update", "_Download and Install")
        dialog.set_response_appearance("update", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_close_response("cancel")
        dialog.connect(
            "response",
            lambda _dialog, response: (
                self._updater.install(release) if response == "update" else None
            ),
        )
        dialog.present()
        return dialog


def open_uri(uri: str) -> None:
    Gio.AppInfo.launch_default_for_uri(uri, None)


def attach_to_about(about: Adw.AboutWindow, controls: Gtk.Widget) -> bool:
    """Put ``controls`` under the version on the About window's first page.

    Adw.AboutWindow has no place for extra widgets, so this finds its version
    button by the "app-version" style class and adds the controls after it.
    False when it is not there, which a test catches on the supported
    libadwaita releases.
    """
    version = _find(about, lambda widget: widget.has_css_class("app-version"))
    parent = version.get_parent() if version is not None else None
    if not isinstance(parent, Gtk.Box):
        return False
    parent.insert_child_after(controls, version)
    return True


def _find(
    widget: Gtk.Widget, wanted: Callable[[Gtk.Widget], bool]
) -> Gtk.Widget | None:
    if wanted(widget):
        return widget
    child = widget.get_first_child()
    while child is not None:
        found = _find(child, wanted)
        if found is not None:
            return found
        child = child.get_next_sibling()
    return None
