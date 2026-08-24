# Support

Search the README and existing issues before opening a report. Include the
application commit or version, Linux distribution, Greaseweazle host-tool
version, device model, drive type, selected format, and sanitised logs.

For a directory-browsing problem, also include the image suffix, detected
low-level format, reported filesystem, and whether the same image opens on its
original computer. Greaseweazle format recognition does not by itself imply
that Greaseweazle-GUI has a reader for the filesystem stored inside that format.
See [Format and filesystem support](docs/FORMAT_SUPPORT.md) before reporting an
empty or unsupported directory.

`gw info` may print a valid local Device block and then report an online GitHub
API or firmware-check failure. Current Greaseweazle-GUI versions keep the device
connected in that case and retain the online warning in the diagnostic log.

Do not upload copyrighted disk images, credentials, private paths, or device
identifiers. Prefer a small generated fixture. Use the issue templates for
reproducible defects and feature requests.

Security reports follow [SECURITY.md](SECURITY.md) and must not be filed as
public support issues. Conduct reports follow
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
