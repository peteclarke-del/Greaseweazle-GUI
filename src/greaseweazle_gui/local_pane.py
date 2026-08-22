"""Nautilus-like local filesystem pane for the dual-pane disk browser."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402


@dataclass(frozen=True, slots=True)
class LocalEntry:
    path: Path
    is_directory: bool
    size: int
    modified: float


class LocalFilePane(Gtk.Box):
    """Browse a local directory and report selections to the file manager."""

    def __init__(
        self,
        on_activated: Callable[[], None],
        on_selection_changed: Callable[[], None],
        prepare_drag: Callable[[Sequence[Path]], Gdk.ContentProvider | None],
        drop_files: Callable[[Sequence[Path]], bool],
        open_file: Callable[[Path], None],
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.current_directory = Path.home()
        self._on_activated = on_activated
        self._on_selection_changed = on_selection_changed
        self._prepare_external_drag = prepare_drag
        self._drop_files = drop_files
        self._open_file = open_file
        self._context_menu: Gtk.PopoverMenu | None = None

        header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_top=8,
            margin_bottom=8,
            margin_start=8,
            margin_end=8,
        )
        up = Gtk.Button.new_from_icon_name("go-up-symbolic")
        up.set_tooltip_text("Parent folder")
        up.connect("clicked", self._go_up)
        header.append(up)
        home = Gtk.Button.new_from_icon_name("user-home-symbolic")
        home.set_tooltip_text("Home folder")
        home.connect("clicked", self._go_home)
        header.append(home)
        self._path = Gtk.Label(xalign=0, hexpand=True, ellipsize=3)
        self._path.add_css_class("heading")
        header.append(self._path)
        self.append(header)
        self.append(Gtk.Separator())

        self._list = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.MULTIPLE,
            activate_on_single_click=False,
        )
        self._list.add_css_class("boxed-list")
        self._list.connect("row-activated", self._row_activated)
        self._list.connect("selected-rows-changed", self._selection_changed)

        click = Gtk.GestureClick()
        click.connect("pressed", self._left_pressed)
        self._list.add_controller(click)
        focus = Gtk.EventControllerFocus()
        focus.connect("enter", lambda _focus: self._on_activated())
        self._list.add_controller(focus)
        drop = Gtk.DropTarget.new(
            Gdk.FileList, Gdk.DragAction.COPY | Gdk.DragAction.MOVE
        )
        drop.connect("drop", self._drop_file_list)
        self._list.add_controller(drop)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self._list)
        self.append(scroller)

        self.status = Gtk.Label(
            xalign=0,
            margin_top=8,
            margin_bottom=8,
            margin_start=10,
            margin_end=10,
            ellipsize=3,
        )
        self.status.add_css_class("dim-label")
        self.append(self.status)
        self.refresh()

    def install_context_menu(self, model: Gio.MenuModel) -> None:
        self._context_menu = Gtk.PopoverMenu.new_from_model(model)
        self._context_menu.set_parent(self._list)
        click = Gtk.GestureClick(button=3)
        click.connect("pressed", self._right_pressed)
        self._list.add_controller(click)

    def do_unroot(self) -> None:
        if self._context_menu is not None:
            self._context_menu.unparent()
        Gtk.Box.do_unroot(self)

    def refresh(self) -> None:
        while row := self._list.get_row_at_index(0):
            self._list.remove(row)
        self._path.set_text(str(self.current_directory))
        try:
            paths = sorted(
                self.current_directory.iterdir(),
                key=lambda path: (not path.is_dir(), path.name.casefold()),
            )
        except OSError as error:
            self.status.set_text(f"Unable to open folder: {error}")
            return

        count = 0
        for path in paths:
            try:
                stat = path.stat()
                entry = LocalEntry(path, path.is_dir(), stat.st_size, stat.st_mtime)
            except OSError:
                entry = LocalEntry(path, path.is_dir(), 0, 0)
            self._list.append(self._make_row(entry))
            count += 1
        if count == 0:
            row = Gtk.ListBoxRow(selectable=False, activatable=False)
            label = Gtk.Label(
                label="This folder is empty",
                margin_top=28,
                margin_bottom=28,
            )
            label.add_css_class("dim-label")
            row.set_child(label)
            self._list.append(row)
        self.status.set_text(f"{count} {'item' if count == 1 else 'items'}")

    def _make_row(self, entry: LocalEntry) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.local_entry = entry  # type: ignore[attr-defined]
        content = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=10,
            margin_top=7,
            margin_bottom=7,
            margin_start=10,
            margin_end=10,
        )
        icon = "folder-symbolic" if entry.is_directory else "text-x-generic-symbolic"
        content.append(Gtk.Image.new_from_icon_name(icon))
        content.append(Gtk.Label(label=entry.path.name, xalign=0, hexpand=True, ellipsize=3))
        if not entry.is_directory:
            size = Gtk.Label(label=GLib.format_size(entry.size), xalign=1)
            size.add_css_class("dim-label")
            content.append(size)
        if entry.modified:
            changed = Gtk.Label(
                label=datetime.fromtimestamp(entry.modified).strftime("%d %b %Y %H:%M"),
                xalign=1,
            )
            changed.add_css_class("dim-label")
            content.append(changed)
        row.set_child(content)
        drag = Gtk.DragSource(actions=Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        drag.connect("prepare", self._prepare_drag, row)
        row.add_controller(drag)
        return row

    def selected_paths(self) -> list[Path]:
        return [
            row.local_entry.path  # type: ignore[attr-defined]
            for row in self._list.get_selected_rows()
            if hasattr(row, "local_entry")
        ]

    def select_all(self) -> None:
        self._list.select_all()

    def open_selected(self) -> None:
        rows = self._list.get_selected_rows()
        if len(rows) == 1:
            self._row_activated(self._list, rows[0])

    def _row_activated(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        if not hasattr(row, "local_entry"):
            return
        entry: LocalEntry = row.local_entry  # type: ignore[attr-defined]
        if entry.is_directory:
            self.current_directory = entry.path
            self.refresh()
        else:
            self._open_file(entry.path)

    def _go_up(self, _button: Gtk.Button) -> None:
        parent = self.current_directory.parent
        if parent != self.current_directory:
            self.current_directory = parent
            self.refresh()

    def _go_home(self, _button: Gtk.Button) -> None:
        self.current_directory = Path.home()
        self.refresh()

    def _left_pressed(
        self, _gesture: Gtk.GestureClick, _presses: int, _x: float, _y: float
    ) -> None:
        self._on_activated()

    def _right_pressed(
        self, _gesture: Gtk.GestureClick, _presses: int, x: float, y: float
    ) -> None:
        self._on_activated()
        row = self._list.get_row_at_y(int(y))
        if row is not None and hasattr(row, "local_entry") and not row.is_selected():
            self._list.unselect_all()
            self._list.select_row(row)
        if self._context_menu is None:
            return
        rectangle = Gdk.Rectangle()
        rectangle.x, rectangle.y, rectangle.width, rectangle.height = int(x), int(y), 1, 1
        self._context_menu.set_pointing_to(rectangle)
        self._context_menu.popup()

    def _selection_changed(self, _list: Gtk.ListBox) -> None:
        self._on_activated()
        self._on_selection_changed()

    def _prepare_drag(
        self, _source: Gtk.DragSource, _x: float, _y: float, row: Gtk.ListBoxRow
    ) -> Gdk.ContentProvider | None:
        if not row.is_selected():
            self._list.unselect_all()
            self._list.select_row(row)
        return self._prepare_external_drag(self.selected_paths())

    def _drop_file_list(
        self,
        _target: Gtk.DropTarget,
        file_list: Gdk.FileList,
        _x: float,
        _y: float,
    ) -> bool:
        paths = []
        for file in file_list.get_files():
            path = file.get_path()
            if path is not None:
                paths.append(Path(path))
        return self._drop_files(paths) if paths else False
