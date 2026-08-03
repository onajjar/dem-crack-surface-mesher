#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_dir="${project_dir}/.venv"
venv_python="${venv_dir}/bin/python"
requirements_path="${project_dir}/requirements.txt"
constraints_path="${project_dir}/constraints-baseline.txt"
export PYTHONNOUSERSITE=1

check_only=0
if [[ $# -gt 1 ]]; then
  echo "Usage: $0 [--check-only]" >&2
  exit 2
fi
if [[ $# -eq 1 ]]; then
  if [[ "$1" != "--check-only" ]]; then
    echo "Unknown option: $1" >&2
    echo "Usage: $0 [--check-only]" >&2
    exit 2
  fi
  check_only=1
fi

for required_path in "${requirements_path}" "${constraints_path}"; do
  if [[ ! -f "${required_path}" ]]; then
    echo "Required setup file is missing: ${required_path}" >&2
    exit 1
  fi
done

if [[ -n "${PYTHON_BIN:-}" ]]; then
  candidate_names=("${PYTHON_BIN}")
else
  candidate_names=("python3" "python")
fi

python_bin=""
python_version=""
rejections=()
for candidate_name in "${candidate_names[@]}"; do
  if ! command -v "${candidate_name}" >/dev/null 2>&1; then
    continue
  fi
  candidate_path="$(command -v "${candidate_name}")"
  if ! candidate_version="$("${candidate_path}" -c \
    'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null)"; then
    rejections+=("${candidate_name}: could not run Python")
    continue
  fi
  if ! "${candidate_path}" -c \
    'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    rejections+=("${candidate_name}: Python ${candidate_version} is older than 3.10")
    continue
  fi
  python_bin="${candidate_path}"
  python_version="${candidate_version}"
  break
done

if [[ -z "${python_bin}" ]]; then
  echo "Python 3.10 or newer was not found." >&2
  for rejection in "${rejections[@]}"; do
    echo "  ${rejection}" >&2
  done
  echo "Install Python, or create a Conda environment with:" >&2
  echo "  conda create -n dem-crack-mesher python=3.11" >&2
  echo "  conda activate dem-crack-mesher" >&2
  exit 1
fi

echo "Project root: ${project_dir}"
echo "Selected Python: ${python_bin} (${python_version})"

if [[ "${check_only}" -eq 1 ]]; then
  echo "Setup check passed. No environment was created."
  exit 0
fi

if [[ ! -x "${venv_python}" ]]; then
  echo "Creating virtual environment: ${venv_dir}"
  "${python_bin}" -m venv "${venv_dir}"
else
  echo "Reusing virtual environment: ${venv_dir}"
fi

if ! venv_version="$("${venv_python}" -c \
  'import sys; print(".".join(map(str, sys.version_info[:3])))')"; then
  echo "The virtual-environment Python executable could not run: ${venv_python}" >&2
  exit 1
fi
if ! "${venv_python}" -c \
  'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "The existing .venv uses Python ${venv_version}; Python 3.10+ is required." >&2
  exit 1
fi

"${venv_python}" -m pip install --no-user --upgrade pip
"${venv_python}" -m pip install --no-user \
  -r "${requirements_path}" \
  -c "${constraints_path}"

echo "Linux environment is ready."
echo "Launch the GUI with: ${project_dir}/run_linux.sh"
echo "Run an INI file with: ${project_dir}/run_linux.sh --headless CONFIG"
