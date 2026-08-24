# Release process

Only the repository maintainer publishes a release.

## Prepare the source

1. Update `project.version` in `pyproject.toml`.
2. Review the pinned Greaseweazle version in
   `packaging/greaseweazle-version.txt`, its source archive checksum in
   `packaging/greaseweazle-source.sha256`, and the Python dependencies in
   `packaging/runtime-requirements.txt`.
3. Update `README.md`, `ROADMAP.md`, `docs/CURRENT_STATUS.md`, and the in-app
   guide for user-visible changes.
4. Regenerate screenshots with `tools/capture_help_screenshots.sh` when the
   illustrated interface changes.
5. Run the complete local verification:

   ```sh
   PYTHONPATH=src python3 -m unittest discover -s tests -v
   python3 -m compileall -q src tests
   ruff check src tests
   ruff format --check src tests
   bash -n greaseweazlegui packaging/*.sh tools/capture_help_screenshots.sh
   desktop-file-validate data/com.github.pclarke.GreaseweazleGUI.desktop
   appstreamcli validate --no-net data/com.github.pclarke.GreaseweazleGUI.metainfo.xml
   ```

## Build locally

On Ubuntu 24.04 with Python 3.12:

```sh
./packaging/build-deb.sh dist
dpkg-deb --info dist/*.deb
dpkg-deb --contents dist/*.deb
```

The build downloads the tagged Greaseweazle source archive, rejects it unless
its SHA-256 matches the reviewed value, and installs pinned Python runtime
dependencies into the private application library. It does not modify the
system Python environment.

## Publish

Merge the reviewed release pull request, then create and push a tag that exactly
matches the project version:

```sh
git tag -s v0.1.0 -m "GreaseWeazleGUI v0.1.0"
git push origin v0.1.0
```

The release workflow verifies the version, runs the tests, builds the wheel and
`.deb`, installs the package on Ubuntu 24.04, exercises the bundled `gw`, creates
`SHA256SUMS`, stores a workflow artifact, and publishes the files in a GitHub
Release. A failed validation or installation prevents publication.
