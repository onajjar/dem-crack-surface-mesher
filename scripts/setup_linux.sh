#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"
venv_dir="${project_dir}/.venv"
export PYTHONNOUSERSITE=1

"${python_bin}" -m venv "${venv_dir}"
"${venv_dir}/bin/python" -m pip install --no-user --upgrade pip
"${venv_dir}/bin/python" -m pip install --no-user \
  -r "${project_dir}/requirements.txt" \
  -c "${project_dir}/constraints-baseline.txt"

echo "Linux environment is ready."
echo "Launch the GUI with: ${project_dir}/run_linux.sh"
echo "Run an INI file with: ${project_dir}/run_linux.sh --headless CONFIG"
