#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ -n "${PYTHONPATH:-}" ]]; then
    export PYTHONPATH="${script_dir}/src:${PYTHONPATH}"
else
    export PYTHONPATH="${script_dir}/src"
fi

exec python3 -m greaseweazle_gui "$@"
