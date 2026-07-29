#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${project_dir}/.venv/bin/python"

if [[ ! -x "${python_bin}" ]]; then
  echo "The local Python environment is missing." >&2
  echo "Run scripts/setup_linux.sh first." >&2
  exit 2
fi

runtime_cache="${TMPDIR:-/tmp}/dem-cfd-crack-matplotlib"
mkdir -p "${runtime_cache}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-${runtime_cache}}"
export PYTHONNOUSERSITE=1

exec "${python_bin}" "${project_dir}/castem_pipeline_gui_scientific.py" "$@"
