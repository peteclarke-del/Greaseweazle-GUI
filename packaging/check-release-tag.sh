#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
project_version="$(cd "${project_dir}" && python3 -c \
    'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
release_tag="${1:-}"

if [[ "${release_tag}" != "v${project_version}" ]]; then
    echo "Release tag ${release_tag:-<missing>} does not match project version v${project_version}." >&2
    exit 1
fi

echo "Release tag ${release_tag} matches project version ${project_version}."
