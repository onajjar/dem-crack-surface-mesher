# Multiple-hole example

This is a real two-hole execution of the unchanged T13 GUI pipeline. It reuses the repository's existing `50 × 50` CSV quartet in [`examples/input`](../input); no geometry or mesh output was fabricated.

![Top view of the real two-hole Cast3M volume mesh](../../docs/assets/multiple-holes-mesh-preview.png)

## Configuration

The complete machine-readable configuration is in [`parameters.json`](parameters.json). The two circles are:

| Hole | `cx` | `cy` | `r` |
|---:|---:|---:|---:|
| 1 | −0.20 | 0.20 | 0.07 |
| 2 | 0.20 | −0.20 | 0.07 |

The run used `num_el_fill=5`, `re_fact_hole=5.0`, `nelem_x=nelem_y=nelem_z=1`, and `re_ti/re_crpa/re_smfa/re_numspa/re_opmin = 60/1/0.05/50/1e-6`. MED, STL, and Gmsh visualization were disabled; integrated BDF merging was enabled.

## Reproduce from a fresh checkout

Install the project dependencies and make Cast3M 25 available at its standard Windows path or through `CASTEM_PATH`. From the repository root, run:

```powershell
python -m pip install -r requirements.txt -c constraints-baseline.txt
python scripts/run_multiple_holes_example.py
```

The runner configures two GUI hole rows and calls `castem_pipeline_gui_t13.App._run` directly. It refuses to reuse a non-empty `_runtime/multiple-holes-output` directory, disables Python bytecode, keeps the Matplotlib cache inside that runtime, and checks the authoritative runtime-integrity manifest before and after execution.

To recreate the preview after a successful run, install the optional rendering dependencies and run:

```powershell
python -m pip install -r requirements-visuals.txt -c constraints-baseline.txt
$env:MPLCONFIGDIR = (Join-Path (Get-Location) '_runtime\multiple-holes-output\.mplconfig')
python -B scripts/render_mesh.py `
  --bdf _runtime\multiple-holes-output\castem_mesh_v.bdf `
  --output docs\assets\multiple-holes-mesh-preview.png `
  --title "Real Cast3M volume mesh — two-hole run" `
  --view top
```

## Recorded output

Cast3M annual version 2025.0 returned process code `0` and stopped at error level `0`. The combined BDF contains `15,672` `GRID`, `5,190` `CHEXA`, `5,710` `CQUAD4`, and `8` `PSHELL` cards. Each of the two separately exported hole surfaces contains `64` `CQUAD4` cards.

The [`output`](output) directory contains the patched DGIBI, the 2.92 MB combined BDF, and a sanitized [`run-report.json`](output/run-report.json) with checksums, timings, card counts, and verification scope. The larger intermediate BDF set and machine-specific solver log remain in the ignored runtime directory.

## Important limitation

After its normal level-0 stop, Cast3M emitted `IEEE_INVALID_FLAG`. The artifacts demonstrate that this input traversed the unchanged GUI-to-Cast3M-to-BDF path and generated two hole surfaces. They are not a mesh-quality, numerical, CFX-import, or FISS-flow validation.
