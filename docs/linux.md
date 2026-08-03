# Linux installation and execution

The maintained Scientific Workbench and headless runner support Linux without
modifying the immutable historical T13 source. A small platform adapter
discovers and starts the native Cast3M and Gmsh executables, translates the
legacy `cmd.exe /c` form used by preserved FISS code, and opens files or
directories with `xdg-open`/`gio`.

## Install

From the repository root:

```bash
./scripts/setup_linux.sh
```

The script resolves the repository from its own location, so it can also be
called from another working directory. It uses `PYTHON_BIN` when set,
otherwise tries `python3` and then `python`; Python 3.10 or newer is required.
It creates or reuses `.venv` and installs `requirements.txt` with the recorded
versions in `constraints-baseline.txt`. To check discovery without creating or
modifying an environment, run:

```bash
./scripts/setup_linux.sh --check-only
```

If Conda is active and you specifically want its interpreter to create
`.venv`, use:

```bash
PYTHON_BIN=python ./scripts/setup_linux.sh
```

Alternatively, install directly in a dedicated Conda environment:

```bash
conda create -n dem-crack-mesher python=3.11
conda activate dem-crack-mesher
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -c constraints-baseline.txt
```

On Debian or Ubuntu, install Tk first if the GUI package is absent:

```bash
sudo apt install python3-venv python3-tk
```

Cast3M and Gmsh remain external applications. They are never downloaded by the
project. Make their launchers discoverable on `PATH`, or set explicit paths:

```bash
export CASTEM_PATH=/path/to/castem25
export GMSH_PATH=/path/to/gmsh
```

`CASTEM_PATH` and `GMSH_PATH` may also name directories containing those
executables. The Cast3M version field accepts both `25` and `2025`.

## Run

Launch the desktop workbench:

```bash
./run_linux.sh
```

Validate a complete INI configuration without starting Cast3M:

```bash
./run_linux.sh --headless examples/scientific-run.ini --validate-only
```

Run the same two-hole conversion through the native Cast3M launcher:

```bash
./run_linux.sh --headless examples/scientific-run.ini
```

The configured working directory receives the canonical CSV copies, generated
DGIBI, Cast3M console log, separate volume/boundary BDFs, merged CFD-facing
BDF, and `headless-run-report.json`. `success: true`, return code zero, an
empty `missing_outputs` list, and a nonempty final BDF are the minimum
completion checks. During the merge, line- or point-collapsed `CQUAD4` records
at exactly closed crack fronts are omitted from the combined BDF. These shells
have zero physical area; the Cast3M volume, fitted faces, and separate raw BDFs
remain unchanged.

Run the bundled raw-DEAP example directly:

```bash
./run_linux.sh --headless examples/deap/1_simple/run.ini --surface-mode deap
gmsh examples/deap/1_simple/results/combined_ti10_crpa1_smfa60_numsp20_opmin10.bdf \
  -check -nopopup
```

The source-free backend remains available when Cast3M is not installed:

```bash
./run_linux.sh --headless examples/python-only-chambers/run.ini
```

## Verified Linux runs

The port was exercised on 2026-07-29 with Python 3.13, Cast3M 2025.0, and
Gmsh 4.13.1:

| Input | Result |
|---|---|
| Raw `examples/deap/1_simple` HDF5 | Cast3M return code `0`, error level `0`, no missing output, maximum fitted/reference error `1.67e-15 m` |
| Raw-DEAP combined BDF | 2,399 `GRID`, 722 `CHEXA`, 798 non-zero `CQUAD4`, 6 `PSHELL`; Gmsh `-check` return code `0` |
| Bundled 50 × 50 CSV with two circular holes | Cast3M return code `0`, no missing output, 64 matching interface edges per hole |
| Two-hole combined BDF | 39,990 `GRID`, 19,480 `CHEXA`, 20,520 `CQUAD4`, 8 `PSHELL`; Gmsh `-check` return code `0` |

## Diagnostics

Confirm launcher discovery:

```bash
command -v castem25
command -v gmsh
.venv/bin/python - <<'PY'
from platform_runtime import resolve_castem_exe, resolve_gmsh_exe

print(resolve_castem_exe("25"))
print(resolve_gmsh_exe())
PY
```

Run the complete source and portability checks:

```bash
.venv/bin/python -m pip install --no-user \
  -r requirements-dev.txt -c constraints-baseline.txt
MPLCONFIGDIR=/tmp/dem-cfd-crack-matplotlib \
  .venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python scripts/verify_baseline.py
```

On a remote machine without an X display, use `--headless`. If a virtual X
server is installed, `xvfb-run -a ./run_linux.sh` can be used for a GUI startup
smoke test.
