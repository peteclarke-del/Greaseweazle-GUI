#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
project_version="$(cd "${project_dir}" && python3 -c \
    'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
runtime_version="$(cd "${project_dir}" && python3 -c \
    'import runpy; print(runpy.run_path("src/greaseweazle_gui/__init__.py")["__version__"])')"
release_tag="${1:-}"

if [[ "${runtime_version}" != "${project_version}" ]]; then
    echo "Runtime version ${runtime_version} does not match project version ${project_version}." >&2
    exit 1
fi
if [[ "${release_tag}" != "v${project_version}" ]]; then
    echo "Release tag ${release_tag:-<missing>} does not match project version v${project_version}." >&2
    exit 1
fi

echo "Release tag ${release_tag}, project metadata, and runtime version all match."
