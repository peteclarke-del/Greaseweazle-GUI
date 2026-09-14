"""The application update: reading the latest release, and fetching and installing its package."""

from __future__ import annotations

import functools
import hashlib
import http.server
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

from greaseweazle_gui import __version__, app_update, releases
from greaseweazle_gui.__main__ import main, restart_command
from greaseweazle_gui.app_update import (
    AppRelease,
    PackageTarget,
    check,
    download,
    install,
    installed_target,
    is_newer,
    parse_version,
    published_sum,
    release_from,
)
from greaseweazle_gui.branding import APPLICATION_NAME, HOMEPAGE, RELEASES_API
from greaseweazle_gui.releases import UpdateCancelled, UpdateError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGING = PROJECT_ROOT / "packaging"
UBUNTU = PackageTarget(
    "ubuntu24.04", "amd64", "Greaseweazle-GUI_{version}_ubuntu24.04_amd64.deb"
)
PACKAGE = "Greaseweazle-GUI_9.0.0_ubuntu24.04_amd64.deb"


def release(
    tag: str = "v9.0.0", assets=(PACKAGE, "SHA256SUMS"), base="http://x", **extra
):
    return {
        "tag_name": tag,
        "name": f"Greaseweazle-GUI {tag} for Linux",
        "html_url": f"{base}/releases/tag/{tag}",
        "body": "Reads more formats.",
        "assets": [
            {"name": name, "browser_download_url": f"{base}/{name}", "size": 1234}
            for name in assets
        ],
        **extra,
    }


def packaging_shell(script: str, *arguments: str) -> str:
    """Run ``script`` in bash after sourcing packaging/package-target.sh."""
    return subprocess.run(
        [
            "bash",
            "-euo",
            "pipefail",
            "-c",
            f'source "{PACKAGING}/package-target.sh"; {script}',
            "bash",
            *arguments,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


class VersionTests(unittest.TestCase):
    def test_only_version_tags_are_versions(self) -> None:
        self.assertEqual(parse_version("v0.2.2"), (0, 2, 2))
        self.assertEqual(parse_version("0.2.2"), (0, 2, 2))
        for tag in ("latest", "v0.2", "v0.2.0-rc1", "v0.2.0.1", "V0.2.0", ""):
            self.assertIsNone(parse_version(tag), tag)

    def test_versions_compare_as_numbers(self) -> None:
        self.assertTrue(is_newer("v0.10.0", "0.9.0"))
        self.assertTrue(is_newer("v1.0.0", "0.99.99"))
        self.assertFalse(is_newer("v0.2.2", "0.2.2"))
        self.assertFalse(is_newer("v0.2.1", "0.2.2"))
        self.assertFalse(is_newer("v0.3.0-rc1", "0.2.2"))

    def test_the_running_version_is_a_release_version(self) -> None:
        self.assertIsNotNone(parse_version(__version__))

    def test_restart_runs_the_same_module_with_the_same_arguments(self) -> None:
        self.assertEqual(
            restart_command(
                ["/usr/lib/greaseweazlegui/greaseweazle_gui/__main__.py", "-x"]
            ),
            [sys.executable, "-m", "greaseweazle_gui", "-x"],
        )

    def test_the_check_reads_this_repositorys_latest_release(self) -> None:
        self.assertEqual(
            app_update.LATEST_URL,
            "https://api.github.com/repos/peteclarke-del/Greaseweazle-GUI/releases/latest",
        )
        self.assertTrue(app_update.LATEST_URL.startswith(RELEASES_API))
        self.assertEqual(
            releases.USER_AGENT, f"{APPLICATION_NAME}/{__version__} (+{HOMEPAGE})"
        )


class RestartTests(unittest.TestCase):
    """main() starts the installed version when the window asks for a restart."""

    def run_main(self, restart: bool) -> mock.Mock:
        class FakeApplication:
            restart_requested = restart

            def run(self, _argv: list[str]) -> int:
                return 0

        module = types.ModuleType("greaseweazle_gui.application")
        module.GreaseweazleApplication = FakeApplication  # type: ignore[attr-defined]
        with (
            mock.patch.dict(sys.modules, {"greaseweazle_gui.application": module}),
            mock.patch("greaseweazle_gui.__main__.os.execv") as execv,
        ):
            self.assertEqual(main(), 0)
        return execv

    def test_a_restart_replaces_the_process_with_the_new_version(self) -> None:
        command = restart_command(sys.argv)
        self.run_main(restart=True).assert_called_once_with(command[0], command)

    def test_without_a_restart_the_application_just_ends(self) -> None:
        self.run_main(restart=False).assert_not_called()


class TargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)
        self.path = self.folder / "package-target"

    def test_the_record_the_package_writes_names_its_system_and_file(self) -> None:
        packaging_shell('write_package_target "$1" arm64', str(self.path))
        target = installed_target(self.path)
        self.assertEqual(
            target,
            PackageTarget(
                "ubuntu24.04",
                "arm64",
                "Greaseweazle-GUI_{version}_ubuntu24.04_arm64.deb",
            ),
        )
        assert target is not None
        self.assertEqual(target.system, "Ubuntu 24.04 arm64")

    def test_the_update_asks_for_the_file_the_build_names(self) -> None:
        for arch in ("amd64", "arm64"):
            with self.subTest(arch=arch):
                packaging_shell(f'write_package_target "$1" {arch}', str(self.path))
                target = installed_target(self.path)
                assert target is not None
                built = packaging_shell(f"package_file_name 1.2.3 {arch}")
                self.assertEqual(target.package_name("1.2.3"), built)
                self.assertEqual(
                    built, f"Greaseweazle-GUI_1.2.3_ubuntu24.04_{arch}.deb"
                )

    def test_the_source_tree_and_a_broken_record_have_no_system(self) -> None:
        self.assertIsNone(installed_target(self.path))
        for text in (
            "distro=ubuntu24.04\narch=amd64\n",
            "distro=ubuntu24.04\npackage=Greaseweazle-GUI_{version}_x.deb\n",
            "distro=ubuntu24.04\narch=amd64\npackage=Greaseweazle-GUI_0.2.2_x.deb\n",
            "distro=ubuntu24.04\narch=amd64\npackage=Greaseweazle-GUI_{version}\n",
        ):
            with self.subTest(text=text):
                self.path.write_text(text, encoding="utf-8")
                self.assertIsNone(installed_target(self.path))
        # The source tree has no package-target beside src/greaseweazle_gui.
        self.assertFalse(app_update.PACKAGE_TARGET.exists())

    def test_other_systems_are_named_for_people(self) -> None:
        self.assertEqual(
            PackageTarget("debian-13", "armhf", "").system, "Debian 13 armhf"
        )

    def test_the_build_writes_the_record_beside_the_application(self) -> None:
        builder = (PACKAGING / "build-deb.sh").read_text(encoding="utf-8")
        self.assertEqual(app_update.PACKAGE_TARGET.name, "package-target")
        self.assertIn(
            'application_lib="${package_root}/usr/lib/greaseweazlegui"', builder
        )
        self.assertIn('source "${project_dir}/packaging/package-target.sh"', builder)
        self.assertIn(
            'write_package_target "${application_lib}/package-target" "${architecture}"',
            builder,
        )
        self.assertIn(
            'artifact="${output_dir}/$(package_file_name "${package_version}" '
            '"${architecture}")"',
            builder,
        )
        self.assertNotIn("Greaseweazle-GUI_", builder)

    def test_the_release_checks_the_record_and_publishes_the_checksums(self) -> None:
        workflow = (PROJECT_ROOT / ".github/workflows/release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("app_update.installed_target()", workflow)
        self.assertIn('"$(basename dist/*.deb)"', workflow)
        self.assertIn(f"sha256sum *.deb *.whl > {app_update.SUMS_NAME}", workflow)


class ReleaseTests(unittest.TestCase):
    def test_a_newer_release_with_this_systems_package_is_installable(self) -> None:
        found = release_from(release(), UBUNTU, current="0.2.2")
        assert found is not None
        self.assertEqual(
            (found.version, found.tag, found.name),
            ("9.0.0", "v9.0.0", "Greaseweazle-GUI 9.0.0"),
        )
        self.assertTrue(found.installable)
        self.assertEqual(found.package_name, PACKAGE)
        self.assertEqual(found.package_url, f"http://x/{PACKAGE}")
        self.assertEqual(found.package_size, 1234)
        self.assertEqual(found.sums_url, "http://x/SHA256SUMS")
        self.assertEqual(found.page_url, "http://x/releases/tag/v9.0.0")
        self.assertEqual(found.notes, "Reads more formats.")

    def test_the_same_or_an_older_version_is_not_offered(self) -> None:
        self.assertIsNone(release_from(release("v0.2.2"), UBUNTU, current="0.2.2"))
        self.assertIsNone(release_from(release("v0.1.0"), UBUNTU, current="0.2.2"))

    def test_another_systems_package_or_the_source_tree_cannot_install(self) -> None:
        arm = PackageTarget(
            "ubuntu24.04", "arm64", "Greaseweazle-GUI_{version}_ubuntu24.04_arm64.deb"
        )
        other = release_from(release(), arm, current="0.2.2")
        assert other is not None
        self.assertFalse(other.installable)
        self.assertEqual(other.package_name, "")
        source = release_from(release(), None, current="0.2.2")
        assert source is not None
        self.assertFalse(source.installable)
        self.assertEqual(source.page_url, "http://x/releases/tag/v9.0.0")
        no_sums = release_from(release(assets=(PACKAGE,)), UBUNTU, current="0.2.2")
        assert no_sums is not None
        self.assertFalse(no_sums.installable)

    def test_a_latest_release_without_a_version_tag_is_a_publishing_mistake(
        self,
    ) -> None:
        with self.assertRaises(UpdateError) as caught:
            release_from(release("nightly"), UBUNTU, current="0.2.2")
        self.assertIn(
            "nightly, is not tagged with a version number", str(caught.exception)
        )

    def test_long_notes_are_shortened(self) -> None:
        found = release_from(release(body="x" * 5000), UBUNTU, current="0.2.2")
        assert found is not None
        self.assertLess(len(found.notes), 2100)
        self.assertTrue(found.notes.endswith("The rest is on the release page."))

    def test_checksum_lines_are_read_as_sha256sum_writes_them(self) -> None:
        digest = "a" * 64
        sums = f"{'b' * 64}  other.deb\n{digest}  {PACKAGE}\n{'c' * 64} *binary.deb\n"
        self.assertEqual(published_sum(sums, PACKAGE), digest)
        self.assertEqual(published_sum(sums, "binary.deb"), "c" * 64)
        self.assertEqual(published_sum(sums, "absent.deb"), "")


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    user_agents: list[str] = []

    def log_message(self, *_args) -> None:
        pass

    def do_GET(self) -> None:
        QuietHandler.user_agents.append(self.headers.get("User-Agent", ""))
        if self.path == "/limited":
            self.send_error(403)
            return
        super().do_GET()


class ServedTests(unittest.TestCase):
    """The check and the download against a local web server."""

    def setUp(self) -> None:
        self.site = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.site)
        self.cache = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cache)
        handler = functools.partial(QuietHandler, directory=str(self.site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_address[1]}"
        QuietHandler.user_agents = []

    def publish(
        self, package: bytes = b"a package", sums: bytes | None = None
    ) -> AppRelease:
        (self.site / PACKAGE).write_bytes(package)
        digest = hashlib.sha256(package).hexdigest()
        (self.site / "SHA256SUMS").write_bytes(
            sums or f"{digest}  {PACKAGE}\n".encode()
        )
        (self.site / "latest").write_text(json.dumps(release(base=self.base)))
        found = check(UBUNTU, url=f"{self.base}/latest", current="0.2.2")
        assert found is not None
        return found

    def test_the_check_finds_the_newer_release(self) -> None:
        found = self.publish()
        self.assertEqual(found.version, "9.0.0")
        self.assertTrue(found.installable)
        self.assertIsNone(check(UBUNTU, url=f"{self.base}/latest", current="9.0.0"))
        self.assertEqual(QuietHandler.user_agents, [releases.USER_AGENT] * 2)

    def test_a_check_that_fails_says_why_and_never_says_newest(self) -> None:
        with self.assertRaises(UpdateError) as caught:
            check(UBUNTU, url="http://127.0.0.1:9/latest")
        self.assertIn("127.0.0.1:9 could not be reached", str(caught.exception))
        with self.assertRaises(UpdateError) as caught:
            check(UBUNTU, url=f"{self.base}/absent")
        self.assertEqual(
            str(caught.exception), "No release has been published on GitHub yet."
        )
        with self.assertRaises(UpdateError) as caught:
            check(UBUNTU, url=f"{self.base}/limited")
        self.assertIn("refused the request (HTTP 403)", str(caught.exception))
        (self.site / "odd").write_text('{"message": "Not Found"}')
        with self.assertRaises(UpdateError) as caught:
            check(UBUNTU, url=f"{self.base}/odd")
        self.assertIn("did not send a release: Not Found.", str(caught.exception))
        (self.site / "broken").write_text("<html>")
        with self.assertRaises(UpdateError) as caught:
            check(UBUNTU, url=f"{self.base}/broken")
        self.assertIn("could not be read", str(caught.exception))

    def test_the_package_is_downloaded_and_checked(self) -> None:
        found = self.publish()
        seen: list[tuple[int, int | None]] = []
        path = download(
            found, lambda done, total: seen.append((done, total)), folder=self.cache
        )
        self.assertEqual(path, self.cache / PACKAGE)
        self.assertEqual(path.read_bytes(), b"a package")
        self.assertEqual(seen[-1], (9, 9))
        self.assertEqual(sorted(p.name for p in self.cache.iterdir()), [PACKAGE])

    def test_a_package_that_does_not_match_its_checksum_is_removed(self) -> None:
        found = self.publish(sums=f"{'0' * 64}  {PACKAGE}\n".encode())
        with self.assertRaises(UpdateError) as caught:
            download(found, folder=self.cache)
        self.assertIn("does not match its published checksum", str(caught.exception))
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_a_package_the_checksums_do_not_list_is_not_downloaded(self) -> None:
        found = self.publish(sums=f"{'0' * 64}  other.deb\n".encode())
        with self.assertRaises(UpdateError) as caught:
            download(found, folder=self.cache)
        self.assertIn("has no line for the package", str(caught.exception))
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_a_missing_package_says_so_and_leaves_nothing(self) -> None:
        found = self.publish()
        (self.site / PACKAGE).unlink()
        with self.assertRaises(UpdateError) as caught:
            download(found, folder=self.cache)
        self.assertIn("sent an unexpected reply (HTTP 404)", str(caught.exception))
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_a_cancelled_download_says_so_and_leaves_nothing(self) -> None:
        found = self.publish(package=b"x" * (releases.CHUNK_SIZE * 3))
        cancel = threading.Event()

        def progress(done: int, _total: int | None) -> None:
            if done:
                cancel.set()

        with self.assertRaises(UpdateCancelled):
            download(found, progress, cancel, folder=self.cache)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_a_release_without_this_systems_package_is_not_downloaded(self) -> None:
        with self.assertRaises(UpdateError):
            download(
                AppRelease("9.0.0", "v9.0.0", "Greaseweazle-GUI 9.0.0", "http://x")
            )

    def test_a_download_cut_short_says_so_and_leaves_nothing(self) -> None:
        class ShortReply:
            headers = {"Content-Length": "100"}

            def __init__(self) -> None:
                self.chunks = [b"x" * 10]

            def __enter__(self):
                return self

            def __exit__(self, *_exc) -> None:
                pass

            def read(self, _size: int) -> bytes:
                return self.chunks.pop() if self.chunks else b""

        target = self.cache / PACKAGE
        with self.assertRaises(UpdateError) as caught:
            releases.download(
                "http://x/p.deb", target, opener=lambda _req, timeout: ShortReply()
            )
        self.assertIn("closed after 10 of 100 bytes", str(caught.exception))
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_only_web_addresses_are_fetched(self) -> None:
        with self.assertRaises(UpdateError) as caught:
            releases.get_reply("file:///etc/hostname")
        self.assertIn("is not a web address", str(caught.exception))

    def test_the_download_folder_follows_the_cache_setting(self) -> None:
        with mock.patch.dict("os.environ", {"XDG_CACHE_HOME": str(self.cache)}):
            self.assertEqual(
                app_update.download_folder(),
                self.cache / "greaseweazle-gui" / "updates",
            )
        with mock.patch.dict("os.environ", {"XDG_CACHE_HOME": "relative"}):
            self.assertEqual(
                app_update.download_folder(),
                Path.home() / ".cache" / "greaseweazle-gui" / "updates",
            )


class InstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)
        self.package = self.folder / PACKAGE
        self.package.write_bytes(b"a package")
        which = {"pkexec": "/usr/bin/pkexec", "apt-get": "/usr/bin/apt-get"}
        patcher = mock.patch.object(app_update.shutil, "which", side_effect=which.get)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_with(self, returncode: int, stderr: str = ""):
        return mock.Mock(
            return_value=subprocess.CompletedProcess(
                [], returncode, stdout="", stderr=stderr
            )
        )

    def test_apt_installs_the_package_with_the_users_password(self) -> None:
        run = self.run_with(0)
        install(self.package, run=run)
        command = run.call_args.args[0]
        self.assertEqual(
            command,
            [
                "/usr/bin/pkexec",
                "/usr/bin/apt-get",
                "install",
                "--yes",
                str(self.package),
            ],
        )
        self.assertFalse(self.package.exists())

    def test_the_install_waits_for_the_password_prompt_and_apt_however_long(
        self,
    ) -> None:
        # pkexec and apt run as root and cannot be stopped from here, so a time
        # limit would report a failure while apt went on to install.
        run = self.run_with(0)
        install(self.package, run=run)
        self.assertNotIn("timeout", run.call_args.kwargs)

    def test_a_dismissed_password_prompt_installs_nothing(self) -> None:
        with self.assertRaises(UpdateCancelled):
            install(self.package, run=self.run_with(126))
        self.assertTrue(self.package.exists())

    def test_a_refusal_or_an_apt_failure_says_what_to_run_by_hand(self) -> None:
        with self.assertRaises(UpdateError) as caught:
            install(self.package, run=self.run_with(127))
        self.assertNotIsInstance(caught.exception, UpdateCancelled)
        self.assertIn("did not allow", str(caught.exception))
        self.assertIn(f"sudo apt install {self.package}", str(caught.exception))
        with self.assertRaises(UpdateError) as caught:
            install(
                self.package, run=self.run_with(100, "E: Unable to locate package\n")
            )
        self.assertNotIsInstance(caught.exception, UpdateCancelled)
        self.assertIn("E: Unable to locate package", str(caught.exception))
        self.assertTrue(self.package.exists())

    def test_without_pkexec_the_command_is_given_instead(self) -> None:
        with (
            mock.patch.object(app_update.shutil, "which", return_value=None),
            self.assertRaises(UpdateError) as caught,
        ):
            install(self.package, run=self.run_with(0))
        self.assertIn("pkexec is not installed", str(caught.exception))
        self.assertIn("sudo apt install", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
