"""Nautilus-style, lazy browser for a disk-image directory."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
import shutil
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .filesystems import DiskContents, FilesystemError, ImageEntry, materialize_entries
from .local_pane import LocalFilePane


class DiskBrowser(Gtk.Box):
    """Browse image metadata and materialize only exported selections."""

    def __init__(
        self,
        contents: DiskContents,
        cache_root: Path,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.contents = contents
        self.cache_root = cache_root
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self._on_done = on_done
        self._active_pane = "disk"
        self._clipboard_paths: list[Path] = []
        self._clipboard_cut = False
        self._dual_pane = True
        self._disk_writable = False
        self._directory_stack: list[tuple[str, tuple[ImageEntry, ...]]] = [
            ("", contents.entries)
        ]

        self._create_actions()
        self.append(self._build_menu_bar())
        self.append(self._build_action_toolbar())
        self.append(Gtk.Separator())

        disk_header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_top=8,
            margin_bottom=8,
            margin_start=8,
            margin_end=8,
        )
        self._up_button = Gtk.Button.new_from_icon_name("go-up-symbolic")
        self._up_button.set_tooltip_text("Parent folder")
        self._up_button.connect("clicked", self._on_up_clicked)
        disk_header.append(self._up_button)
        root_button = Gtk.Button.new_from_icon_name("drive-removable-media-symbolic")
        root_button.set_tooltip_text("Disk root")
        root_button.connect("clicked", self._on_root_clicked)
        disk_header.append(root_button)
        self._path_label = Gtk.Label(xalign=0, hexpand=True, ellipsize=3)
        self._path_label.add_css_class("heading")
        disk_header.append(self._path_label)

        self._list = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.MULTIPLE,
            activate_on_single_click=False,
        )
        self._list.add_css_class("boxed-list")
        self._list.connect("row-activated", self._on_row_activated)
        self._list.connect("selected-rows-changed", self._disk_selection_changed)
        left_click = Gtk.GestureClick()
        left_click.connect("pressed", lambda *_args: self._set_active_pane("disk"))
        self._list.add_controller(left_click)
        focus = Gtk.EventControllerFocus()
        focus.connect("enter", lambda _focus: self._set_active_pane("disk"))
        self._list.add_controller(focus)
        gesture = Gtk.GestureClick(button=3)
        gesture.connect("pressed", self._on_right_click)
        self._list.add_controller(gesture)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self._list)

        self._status = Gtk.Label(
            xalign=0,
            margin_top=8,
            margin_bottom=8,
            margin_start=12,
            margin_end=12,
        )
        self._status.add_css_class("dim-label")

        disk_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        disk_box.set_hexpand(True)
        disk_box.append(disk_header)
        disk_box.append(Gtk.Separator())
        disk_box.append(scroller)
        disk_box.append(self._status)
        self._local = LocalFilePane(
            on_activated=lambda: self._set_active_pane("local"),
            on_selection_changed=self._update_action_state,
            prepare_drag=lambda paths: self._file_provider(paths),
            drop_files=self._drop_paths_to_local,
            open_file=self._open_local_file,
        )
        self._local.set_hexpand(True)
        self._copy_to_local_button = Gtk.Button(
            label=">",
            tooltip_text="Copy selected disk items to the current local folder",
        )
        self._copy_to_local_button.add_css_class("suggested-action")
        self._copy_to_local_button.connect("clicked", self._copy_disk_to_local)
        self._copy_to_disk_button = Gtk.Button(
            label="<",
            tooltip_text="Copy selected local items into the disk image",
        )
        self._copy_to_disk_button.connect("clicked", self._copy_local_to_disk)
        self._transfer_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            valign=Gtk.Align.CENTER,
            margin_start=6,
            margin_end=6,
        )
        self._transfer_box.append(self._copy_to_local_button)
        self._transfer_box.append(self._copy_to_disk_button)

        self._pane_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=0,
            vexpand=True,
        )
        self._pane_box.append(disk_box)
        self._pane_box.append(self._transfer_box)
        self._pane_box.append(self._local)
        self.append(self._pane_box)

        context_model = self._context_menu_model()
        self._context_menu = Gtk.PopoverMenu.new_from_model(context_model)
        self._context_menu.set_parent(self._list)
        self._local.install_context_menu(context_model)
        self.get_clipboard().connect(
            "changed", lambda _clipboard: self._update_action_state()
        )

        self._show_current_directory()
        self._update_action_state()

    def _create_actions(self) -> None:
        group = Gio.SimpleActionGroup()
        callbacks = {
            "open": self._action_open,
            "new-folder": self._action_new_folder,
            "rename": self._action_rename,
            "properties": self._action_properties,
            "cut": self._action_cut,
            "copy": self._action_copy,
            "paste": self._action_paste,
            "trash": self._action_trash,
            "select-all": self._action_select_all,
            "refresh": self._action_refresh,
            "done": self._action_done,
        }
        self._actions: dict[str, Gio.SimpleAction] = {}
        for name, callback in callbacks.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            group.add_action(action)
            self._actions[name] = action
        dual = Gio.SimpleAction.new_stateful(
            "dual-pane", None, GLib.Variant("b", True)
        )
        dual.connect("activate", self._action_dual_pane)
        group.add_action(dual)
        self._actions["dual-pane"] = dual
        self.insert_action_group("manager", group)

        shortcuts = Gtk.ShortcutController()
        shortcuts.set_scope(Gtk.ShortcutScope.LOCAL)
        for trigger, action_name in (
            ("<Control>o", "open"),
            ("<Control>x", "cut"),
            ("<Control>c", "copy"),
            ("<Control>v", "paste"),
            ("<Control>a", "select-all"),
            ("F2", "rename"),
            ("Delete", "trash"),
            ("F5", "refresh"),
        ):
            shortcuts.add_shortcut(
                Gtk.Shortcut.new(
                    Gtk.ShortcutTrigger.parse_string(trigger),
                    Gtk.NamedAction.new(f"manager.{action_name}"),
                )
            )
        self.add_controller(shortcuts)

    @staticmethod
    def _menu_item(label: str, action: str) -> Gio.MenuItem:
        return Gio.MenuItem.new(label, action)

    def _build_menu_bar(self) -> Gtk.PopoverMenuBar:
        root = Gio.Menu()
        file_menu = Gio.Menu()
        file_menu.append_item(self._menu_item("Open", "manager.open"))
        file_menu.append_item(self._menu_item("New Folder", "manager.new-folder"))
        file_menu.append_item(self._menu_item("Rename", "manager.rename"))
        file_menu.append_item(self._menu_item("Properties", "manager.properties"))
        file_menu.append_item(self._menu_item("Move to Trash", "manager.trash"))
        file_menu.append_item(self._menu_item("Close Browser", "manager.done"))
        root.append_submenu("File", file_menu)

        edit_menu = Gio.Menu()
        edit_menu.append_item(self._menu_item("Cut", "manager.cut"))
        edit_menu.append_item(self._menu_item("Copy", "manager.copy"))
        edit_menu.append_item(self._menu_item("Paste", "manager.paste"))
        edit_menu.append_item(self._menu_item("Select All", "manager.select-all"))
        root.append_submenu("Edit", edit_menu)

        view_menu = Gio.Menu()
        view_menu.append_item(self._menu_item("Dual Pane", "manager.dual-pane"))
        view_menu.append_item(self._menu_item("Refresh", "manager.refresh"))
        root.append_submenu("View", view_menu)
        return Gtk.PopoverMenuBar.new_from_model(root)

    def _build_action_toolbar(self) -> Gtk.Widget:
        toolbar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=4,
            margin_top=6,
            margin_bottom=6,
            margin_start=8,
            margin_end=8,
        )
        for icon, label, action in (
            ("document-open-symbolic", "Open", "open"),
            ("folder-new-symbolic", "New Folder", "new-folder"),
            ("document-edit-symbolic", "Rename", "rename"),
            ("edit-cut-symbolic", "Cut", "cut"),
            ("edit-copy-symbolic", "Copy", "copy"),
            ("edit-paste-symbolic", "Paste", "paste"),
            ("user-trash-symbolic", "Trash", "trash"),
            ("view-refresh-symbolic", "Refresh", "refresh"),
        ):
            button = Gtk.Button.new_from_icon_name(icon)
            button.set_tooltip_text(label)
            button.set_action_name(f"manager.{action}")
            toolbar.append(button)
        spacer = Gtk.Box(hexpand=True)
        toolbar.append(spacer)
        dual = Gtk.ToggleButton(label="Dual Pane", active=True)
        dual.set_icon_name("view-dual-symbolic")
        dual.set_action_name("manager.dual-pane")
        toolbar.append(dual)
        if self._on_done is not None:
            done = Gtk.Button(label="Done")
            done.set_action_name("manager.done")
            toolbar.append(done)
        return toolbar

    def _context_menu_model(self) -> Gio.MenuModel:
        menu = Gio.Menu()
        menu.append_item(self._menu_item("Open", "manager.open"))
        menu.append_item(self._menu_item("Cut", "manager.cut"))
        menu.append_item(self._menu_item("Copy", "manager.copy"))
        menu.append_item(self._menu_item("Paste", "manager.paste"))
        menu.append_item(self._menu_item("New Folder", "manager.new-folder"))
        menu.append_item(self._menu_item("Rename", "manager.rename"))
        menu.append_item(self._menu_item("Properties", "manager.properties"))
        menu.append_item(self._menu_item("Move to Trash", "manager.trash"))
        menu.append_item(self._menu_item("Select All", "manager.select-all"))
        return menu

    def _set_active_pane(self, pane: str) -> None:
        self._active_pane = pane
        if pane == "disk":
            self._status.set_text(
                self._status.get_text().split(" • Active pane")[0] + " • Active pane"
            )
            self._local.status.remove_css_class("accent")
            self._status.add_css_class("accent")
        else:
            self._status.remove_css_class("accent")
            self._local.status.add_css_class("accent")
        self._update_action_state()

    def _disk_selection_changed(self, _list: Gtk.ListBox) -> None:
        self._set_active_pane("disk")

    def _update_action_state(self) -> None:
        if not hasattr(self, "_local"):
            return
        disk_selected = bool(self._selected_entries())
        local_selected = bool(self._local.selected_paths())
        local_active = self._active_pane == "local"
        self._actions["open"].set_enabled(
            local_selected if local_active else disk_selected
        )
        self._actions["copy"].set_enabled(
            local_selected if local_active else disk_selected
        )
        self._actions["cut"].set_enabled(local_active and local_selected)
        self._actions["trash"].set_enabled(local_active and local_selected)
        self._actions["rename"].set_enabled(
            local_active and len(self._local.selected_paths()) == 1
        )
        self._actions["properties"].set_enabled(
            local_selected if local_active else disk_selected
        )
        self._actions["paste"].set_enabled(
            local_active
            and (
                bool(self._clipboard_paths)
                or self.get_clipboard().get_formats().contain_gtype(Gdk.FileList)
            )
        )
        self._actions["new-folder"].set_enabled(local_active)
        self._actions["done"].set_enabled(self._on_done is not None)
        self._copy_to_local_button.set_sensitive(disk_selected)
        self._copy_to_disk_button.set_sensitive(
            self._disk_writable and local_selected
        )

    def _action_open(self, _action: Gio.SimpleAction, _parameter: object) -> None:
        if self._active_pane == "local":
            self._local.open_selected()
            return
        rows = self._list.get_selected_rows()
        if len(rows) == 1:
            self._on_row_activated(self._list, rows[0])

    def _action_copy(self, _action: Gio.SimpleAction, _parameter: object) -> None:
        if self._active_pane == "disk":
            self._copy_selected(None)
            return
        paths = self._local.selected_paths()
        self._set_clipboard(paths, cut=False)
        self._local.status.set_text(f"Copied {len(paths)} item(s)")

    def _action_cut(self, _action: Gio.SimpleAction, _parameter: object) -> None:
        paths = self._local.selected_paths()
        self._set_clipboard(paths, cut=True)
        self._local.status.set_text(f"Cut {len(paths)} item(s) — choose Paste to move")

    def _action_paste(self, _action: Gio.SimpleAction, _parameter: object) -> None:
        if self._active_pane != "local":
            return
        if not self._clipboard_paths:
            self.get_clipboard().read_value_async(
                Gdk.FileList,
                GLib.PRIORITY_DEFAULT,
                None,
                self._clipboard_files_ready,
            )
            return
        sources = list(self._clipboard_paths)
        cut = self._clipboard_cut
        destination = self._local.current_directory
        self._local.status.set_text("Moving files…" if cut else "Copying files…")

        def worker() -> None:
            try:
                for source in sources:
                    target = self._available_target(destination / source.name)
                    source_resolved = source.resolve()
                    destination_resolved = destination.resolve()
                    if source.is_dir() and (
                        destination_resolved == source_resolved
                        or source_resolved in destination_resolved.parents
                    ):
                        raise OSError("A folder cannot be copied into itself.")
                    if cut:
                        shutil.move(str(source), str(target))
                    elif source.is_dir():
                        shutil.copytree(source, target)
                    else:
                        shutil.copy2(source, target)
            except OSError as error:
                GLib.idle_add(self._finish_file_operation, f"File operation failed: {error}", False)
                return
            if cut:
                self._clipboard_paths.clear()
                self._clipboard_cut = False
            verb = "Moved" if cut else "Copied"
            GLib.idle_add(
                self._finish_file_operation, f"{verb} {len(sources)} item(s)", True
            )

        threading.Thread(target=worker, name="file-manager-paste", daemon=True).start()

    def _clipboard_files_ready(
        self, clipboard: Gdk.Clipboard, result: Gio.AsyncResult
    ) -> None:
        try:
            file_list = clipboard.read_value_finish(result)
        except GLib.Error as error:
            self._local.status.set_text(f"Could not read clipboard: {error.message}")
            return
        paths = []
        if isinstance(file_list, Gdk.FileList):
            for file in file_list.get_files():
                path = file.get_path()
                if path is not None:
                    paths.append(Path(path))
        if not paths:
            self._local.status.set_text("The clipboard does not contain local files")
            return
        self._clipboard_paths = paths
        self._clipboard_cut = False
        self._action_paste(self._actions["paste"], None)

    def _drop_paths_to_local(self, paths: Sequence[Path]) -> bool:
        if not paths:
            return False
        self._set_active_pane("local")
        self._set_clipboard(paths, cut=False)
        self._action_paste(self._actions["paste"], None)
        return True

    def _open_local_file(self, path: Path) -> None:
        try:
            Gio.AppInfo.launch_default_for_uri(path.as_uri(), None)
        except GLib.Error as error:
            self._local.status.set_text(f"Could not open {path.name}: {error.message}")

    def _action_trash(self, _action: Gio.SimpleAction, _parameter: object) -> None:
        paths = self._local.selected_paths()
        if not paths:
            return
        self._local.status.set_text("Moving selection to Trash…")

        def worker() -> None:
            try:
                for path in paths:
                    Gio.File.new_for_path(str(path)).trash(None)
            except GLib.Error as error:
                GLib.idle_add(self._finish_file_operation, f"Could not use Trash: {error.message}", False)
                return
            GLib.idle_add(
                self._finish_file_operation,
                f"Moved {len(paths)} item(s) to Trash",
                True,
            )

        threading.Thread(target=worker, name="file-manager-trash", daemon=True).start()

    def _action_new_folder(self, _action: Gio.SimpleAction, _parameter: object) -> None:
        if self._active_pane != "local":
            return
        self._request_name("Create New Folder", "New Folder", self._create_folder)

    def _create_folder(self, name: str) -> None:
        target = self._local.current_directory / name
        if target.exists():
            self._local.status.set_text(f"{name} already exists")
            return
        try:
            target.mkdir()
        except OSError as error:
            self._local.status.set_text(f"Could not create folder: {error}")
            return
        self._local.refresh()
        self._local.status.set_text(f"Created {target.name}")

    def _action_rename(self, _action: Gio.SimpleAction, _parameter: object) -> None:
        paths = self._local.selected_paths()
        if self._active_pane != "local" or len(paths) != 1:
            return
        source = paths[0]
        self._request_name(
            "Rename Item",
            source.name,
            lambda name: self._rename_path(source, name),
        )

    def _rename_path(self, source: Path, name: str) -> None:
        target = source.with_name(name)
        if target.exists() and target != source:
            self._local.status.set_text(f"{name} already exists")
            return
        try:
            source.rename(target)
        except OSError as error:
            self._local.status.set_text(f"Could not rename item: {error}")
            return
        self._local.refresh()
        self._local.status.set_text(f"Renamed to {name}")

    def _request_name(
        self, title: str, initial: str, callback: Callable[[str], None]
    ) -> None:
        root = self.get_root()
        parent = root if isinstance(root, Gtk.Window) else None
        dialog = Adw.MessageDialog.new(parent, title, "Enter a name.")
        entry = Gtk.Entry(text=initial, activates_default=True)
        entry.select_region(0, -1)
        entry.set_margin_top(8)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("accept", "Save")
        dialog.set_response_appearance("accept", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("accept")
        dialog.set_close_response("cancel")

        def respond(_dialog: Adw.MessageDialog, response: str) -> None:
            name = entry.get_text().strip()
            if response != "accept" or not name:
                return
            if "/" in name or name in {".", ".."}:
                self._local.status.set_text("The name is not valid")
                return
            callback(name)

        dialog.connect("response", respond)
        dialog.present()

    def _action_properties(
        self, _action: Gio.SimpleAction, _parameter: object
    ) -> None:
        if self._active_pane == "local":
            paths = self._local.selected_paths()
            if not paths:
                return
            path = paths[0]
            try:
                stat = path.stat()
                detail = (
                    f"Location: {path.parent}\n"
                    f"Type: {'Folder' if path.is_dir() else 'File'}\n"
                    f"Size: {GLib.format_size(stat.st_size)}"
                )
            except OSError as error:
                detail = f"Location: {path}\n\n{error}"
            title = path.name
        else:
            entries = self._selected_entries()
            if not entries:
                return
            entry = entries[0]
            title = entry.name
            detail = (
                "Location: Disk image (read-only)\n"
                f"Type: {'Folder' if entry.is_directory else 'File'}\n"
                f"Size: {GLib.format_size(entry.size)}"
            )
        root = self.get_root()
        parent = root if isinstance(root, Gtk.Window) else None
        dialog = Adw.MessageDialog.new(parent, title, detail)
        dialog.add_response("close", "Close")
        dialog.present()

    def _action_select_all(self, _action: Gio.SimpleAction, _parameter: object) -> None:
        if self._active_pane == "local":
            self._local.select_all()
        else:
            self._list.select_all()

    def _action_refresh(self, _action: Gio.SimpleAction, _parameter: object) -> None:
        if self._active_pane == "local":
            self._local.refresh()
        else:
            self._show_current_directory()

    def _action_done(self, _action: Gio.SimpleAction, _parameter: object) -> None:
        if self._on_done is not None:
            self._on_done()

    def _action_dual_pane(
        self, action: Gio.SimpleAction, _parameter: object
    ) -> None:
        self._dual_pane = not action.get_state().get_boolean()
        action.set_state(GLib.Variant("b", self._dual_pane))
        self._local.set_visible(self._dual_pane)
        self._transfer_box.set_visible(self._dual_pane)
        if not self._dual_pane and self._active_pane == "local":
            self._set_active_pane("disk")

    def _copy_disk_to_local(self, _button: Gtk.Button) -> None:
        entries = self._selected_entries()
        if not entries:
            return
        try:
            paths = self._materialize(entries)
        except (FilesystemError, OSError) as error:
            self._status.set_text(f"Could not read selection: {error}")
            return
        self._drop_paths_to_local(paths)

    def _copy_local_to_disk(self, _button: Gtk.Button) -> None:
        if not self._disk_writable:
            self._local.status.set_text("The disk image is read-only")
            return

    def _set_clipboard(self, paths: Sequence[Path], *, cut: bool) -> None:
        self._clipboard_paths = list(paths)
        self._clipboard_cut = cut
        provider = self._file_provider(paths, cut=cut)
        if provider is not None:
            self.get_clipboard().set_content(provider)
        self._update_action_state()

    @staticmethod
    def _available_target(target: Path) -> Path:
        if not target.exists():
            return target
        stem = target.stem
        suffix = target.suffix
        counter = 2
        while True:
            candidate = target.with_name(f"{stem} ({counter}){suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def _finish_file_operation(self, message: str, refresh: bool) -> bool:
        if refresh:
            self._local.refresh()
        self._local.status.set_text(message)
        self._update_action_state()
        return GLib.SOURCE_REMOVE

    def do_unroot(self) -> None:
        self._context_menu.unparent()
        Gtk.Box.do_unroot(self)

    def _show_current_directory(self) -> None:
        # ListBox has internal widgets which are returned by get_first_child().
        # Remove actual rows by index to avoid an endless GTK warning loop.
        while row := self._list.get_row_at_index(0):
            self._list.remove(row)

        entries = sorted(
            self._directory_stack[-1][1],
            key=lambda entry: (not entry.is_directory, entry.name.casefold()),
        )
        for entry in entries:
            self._list.append(self._make_row(entry))
        if not entries:
            empty_row = Gtk.ListBoxRow(selectable=False, activatable=False)
            empty_page = Adw.StatusPage(
                icon_name="folder-open-symbolic",
                title="No files found",
                description="The disk directory is empty or contains no visible files.",
            )
            empty_page.set_vexpand(True)
            empty_row.set_child(empty_page)
            self._list.append(empty_row)

        parts = [name for name, _entries in self._directory_stack if name]
        self._path_label.set_text("/" if not parts else f"/{'/'.join(parts)}")
        self._up_button.set_sensitive(len(self._directory_stack) > 1)
        noun = "item" if len(entries) == 1 else "items"
        self._status.set_text(f"{len(entries)} {noun} • contents read directly from image")

    def _make_row(self, entry: ImageEntry) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.image_entry = entry  # type: ignore[attr-defined]
        content = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            margin_top=9,
            margin_bottom=9,
            margin_start=12,
            margin_end=12,
        )
        icon_name = "folder-symbolic" if entry.is_directory else "text-x-generic-symbolic"
        content.append(Gtk.Image.new_from_icon_name(icon_name))
        content.append(Gtk.Label(label=entry.name, xalign=0, hexpand=True, ellipsize=3))
        if not entry.is_directory:
            size_label = Gtk.Label(label=GLib.format_size(entry.size), xalign=1)
            size_label.add_css_class("dim-label")
            content.append(size_label)
        row.set_child(content)

        drag_source = Gtk.DragSource(actions=Gdk.DragAction.COPY)
        drag_source.connect("prepare", self._prepare_drag, row)
        row.add_controller(drag_source)
        return row

    def _selected_entries(self) -> list[ImageEntry]:
        return [
            row.image_entry  # type: ignore[attr-defined]
            for row in self._list.get_selected_rows()
        ]

    def _cache_directory(self) -> Path:
        parts = [name for name, _entries in self._directory_stack if name]
        return self.cache_root.joinpath(*parts)

    def _materialize(self, entries: Sequence[ImageEntry]) -> list[Path]:
        destination = self._cache_directory()
        materialize_entries(entries, destination)
        return [destination / entry.name for entry in entries]

    @staticmethod
    def _file_provider(
        paths: Sequence[Path], *, cut: bool = False
    ) -> Gdk.ContentProvider | None:
        if not paths:
            return None
        files = [Gio.File.new_for_path(str(path)) for path in paths]
        standard_provider = Gdk.ContentProvider.new_for_value(
            Gdk.FileList.new_from_list(files)
        )
        operation = "cut" if cut else "copy"
        gnome_payload = operation + "\n" + "\n".join(file.get_uri() for file in files) + "\n"
        gnome_provider = Gdk.ContentProvider.new_for_bytes(
            "x-special/gnome-copied-files",
            GLib.Bytes.new(gnome_payload.encode("utf-8")),
        )
        return Gdk.ContentProvider.new_union([standard_provider, gnome_provider])

    def _prepare_drag(
        self, _source: Gtk.DragSource, _x: float, _y: float, row: Gtk.ListBoxRow
    ) -> Gdk.ContentProvider | None:
        if not row.is_selected():
            self._list.unselect_all()
            self._list.select_row(row)
        try:
            paths = self._materialize(self._selected_entries())
        except (FilesystemError, OSError) as error:
            self._status.set_text(f"Could not copy selection: {error}")
            return None
        return self._file_provider(paths)

    def _copy_selected(self, _button: Gtk.Button | None) -> None:
        entries = self._selected_entries()
        if not entries:
            self._status.set_text("Select one or more files to copy")
            return
        try:
            paths = self._materialize(entries)
        except (FilesystemError, OSError) as error:
            self._status.set_text(f"Could not copy selection: {error}")
            return
        self._set_clipboard(paths, cut=False)
        noun = "item" if len(paths) == 1 else "items"
        self._status.set_text(f"Copied {len(paths)} {noun} — paste into a folder in Files")

    def _copy_from_menu(self, button: Gtk.Button) -> None:
        self._context_menu.popdown()
        self._copy_selected(button)

    def _on_right_click(
        self, _gesture: Gtk.GestureClick, _presses: int, x: float, y: float
    ) -> None:
        row = self._list.get_row_at_y(int(y))
        self._set_active_pane("disk")
        if row is None:
            return
        if not row.is_selected():
            self._list.unselect_all()
            self._list.select_row(row)
        rectangle = Gdk.Rectangle()
        rectangle.x, rectangle.y, rectangle.width, rectangle.height = int(x), int(y), 1, 1
        self._context_menu.set_pointing_to(rectangle)
        self._context_menu.popup()

    def _on_row_activated(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        entry = row.image_entry  # type: ignore[attr-defined]
        if entry.is_directory:
            self._directory_stack.append((entry.name, entry.children))
            self._show_current_directory()
            return
        try:
            path = self._materialize([entry])[0]
            Gio.AppInfo.launch_default_for_uri(path.as_uri(), None)
        except (FilesystemError, OSError, GLib.Error) as error:
            self._status.set_text(f"Could not open {entry.name}: {error}")

    def _on_up_clicked(self, _button: Gtk.Button) -> None:
        if len(self._directory_stack) > 1:
            self._directory_stack.pop()
            self._show_current_directory()

    def _on_root_clicked(self, _button: Gtk.Button) -> None:
        if len(self._directory_stack) > 1:
            self._directory_stack = self._directory_stack[:1]
            self._show_current_directory()
