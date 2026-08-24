#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:-${project_dir}/dist}"
python_command="${PYTHON:-python3}"

package_version="$(cd "${project_dir}" && "${python_command}" -c \
    'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
greaseweazle_version="$(tr -d '[:space:]' < "${project_dir}/packaging/greaseweazle-version.txt")"
greaseweazle_sha256="$(tr -d '[:space:]' < "${project_dir}/packaging/greaseweazle-source.sha256")"
python_version="$(${python_command} -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
architecture="$(dpkg --print-architecture)"

if [[ "${python_version}" != "3.12" ]]; then
    echo "The Ubuntu 24.04 package must be built with Python 3.12, not ${python_version}." >&2
    exit 1
fi
if [[ "${package_version}" == *-* ]]; then
    echo "The project version must not contain a Debian revision separator: ${package_version}" >&2
    exit 1
fi

build_dir="$(mktemp -d)"
trap 'rm -rf -- "${build_dir}"' EXIT
greaseweazle_archive="${build_dir}/greaseweazle-v${greaseweazle_version}.tar.gz"
package_root="${build_dir}/greaseweazlegui_${package_version}_${architecture}"
application_lib="${package_root}/usr/lib/greaseweazlegui"

curl --fail --location --silent --show-error \
    --output "${greaseweazle_archive}" \
    "https://github.com/keirf/greaseweazle/archive/refs/tags/v${greaseweazle_version}.tar.gz"
echo "${greaseweazle_sha256}  ${greaseweazle_archive}" | sha256sum --check --status

install -d \
    "${application_lib}/bin" \
    "${package_root}/usr/bin" \
    "${package_root}/usr/share/applications" \
    "${package_root}/usr/share/metainfo" \
    "${package_root}/usr/lib/udev/rules.d" \
    "${package_root}/usr/share/doc/greaseweazlegui" \
    "${package_root}/DEBIAN" \
    "${output_dir}"

"${python_command}" -m pip install \
    --disable-pip-version-check \
    --no-compile \
    --no-deps \
    --ignore-installed \
    --target "${application_lib}" \
    --requirement "${project_dir}/packaging/runtime-requirements.txt"
SETUPTOOLS_SCM_PRETEND_VERSION="${greaseweazle_version}" \
SETUPTOOLS_SCM_PRETEND_VERSION_FOR_GREASEWEAZLE="${greaseweazle_version}" \
"${python_command}" -m pip install \
    --disable-pip-version-check \
    --no-compile \
    --no-deps \
    --target "${application_lib}" \
    "${project_dir}" \
    "${greaseweazle_archive}"

# Wheels may preserve a cooperative build umask. Installed application files
# must never remain group writable under /usr.
chmod -R go-w "${application_lib}"
rm -rf -- "${application_lib}/bin"
install -d "${application_lib}/bin"
install -m 0755 "${project_dir}/packaging/gw" "${application_lib}/bin/gw"
install -m 0644 "${project_dir}/packaging/gw_entry.py" "${application_lib}/gw_entry.py"
install -m 0755 "${project_dir}/packaging/greaseweazle-gui" \
    "${package_root}/usr/bin/greaseweazle-gui"
install -m 0644 "${project_dir}/data/com.github.pclarke.GreaseweazleGUI.desktop" \
    "${package_root}/usr/share/applications/com.github.pclarke.GreaseweazleGUI.desktop"
install -m 0644 "${project_dir}/data/com.github.pclarke.GreaseweazleGUI.metainfo.xml" \
    "${package_root}/usr/share/metainfo/com.github.pclarke.GreaseweazleGUI.metainfo.xml"
install -m 0644 "${project_dir}/packaging/49-greaseweazle.rules" \
    "${package_root}/usr/lib/udev/rules.d/49-greaseweazle.rules"
install -m 0644 "${project_dir}/README.md" \
    "${package_root}/usr/share/doc/greaseweazlegui/README.md"
install -m 0644 "${project_dir}/SECURITY.md" \
    "${package_root}/usr/share/doc/greaseweazlegui/SECURITY.md"
tar -xOf "${greaseweazle_archive}" \
    "greaseweazle-${greaseweazle_version}/COPYING" \
    > "${package_root}/usr/share/doc/greaseweazlegui/COPYING.greaseweazle"
chmod 0644 "${package_root}/usr/share/doc/greaseweazlegui/COPYING.greaseweazle"
install -m 0755 "${project_dir}/packaging/postinst" "${package_root}/DEBIAN/postinst"
install -m 0755 "${project_dir}/packaging/postrm" "${package_root}/DEBIAN/postrm"

installed_size="$(du -sk "${package_root}/usr" | cut -f1)"
cat > "${package_root}/DEBIAN/control" <<EOF
Package: greaseweazlegui
Version: ${package_version}
Section: utils
Priority: optional
Architecture: ${architecture}
Installed-Size: ${installed_size}
Maintainer: Pete Clarke <peteclarke-del@users.noreply.github.com>
Depends: python3 (>= 3.12), python3 (<< 3.13), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1
Homepage: https://github.com/peteclarke-del/Greaseweazle-GUI
Description: Native Linux interface for Greaseweazle disk operations
 Greaseweazle-GUI reads, writes, creates, inspects, and browses floppy disk
 images using Greaseweazle hardware. The package includes Greaseweazle Host
 Tools ${greaseweazle_version} and the Linux device-access rules.
EOF

artifact="${output_dir}/Greaseweazle-GUI_${package_version}_ubuntu24.04_${architecture}.deb"
dpkg-deb --root-owner-group --build "${package_root}" "${artifact}"
echo "Created ${artifact}"
