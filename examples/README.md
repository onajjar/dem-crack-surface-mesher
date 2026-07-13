# Baseline examples

`input/` contains an existing four-file input quartet from the supplied project. The files are copied byte-for-byte, contain only headerless comma-delimited numeric matrices, and are included to exercise the unchanged T13 pipeline. They are not synthetic, and no scientific provenance or validation claim is attached to them.

| Scenario | Holes | Verified artifacts |
|---|---:|---|
| [Baseline run](#run-it-through-the-gui) | 0 | `output/` |
| [Multiple-hole run](multiple-holes/README.md) | 2 | `multiple-holes/output/` |

## Shared input summary

All four matrices are `50 × 50`.

| File | Role | SHA-256 |
|---|---|---|
| `xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv` | x-coordinate grid, range −0.6 to 0.6 | `e921f1c90d704df8e981ccb85a75b2ac2a50ec742a193341064cc1e3d04c7a09` |
| `yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv` | y-coordinate grid, range −0.45 to 0.45 | `89f2f63aa4707b761582a4a15ff8709071ebcec87332ee27ac2437c837f9a682` |
| `zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv` | upper z surface | `cb2fb2db6d2d8e6af00da6f34a98cb521a3e23c4b9fda6ecba0022f9c36c55c5` |
| `zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv` | lower z surface | `6b38423281dad212107b29630271760169b49610f43ba30f0cf9b33c4c6417b4` |

For this quartet, `zfit_zmax - zfit_zmin` is positive at every grid point and ranges from approximately `6.05e-6` to `3.18e-4` in the input coordinate units. This is a structural observation only, not a physical acceptance criterion.

## Run it through the GUI

Start from the repository root:

```powershell
python castem_pipeline_gui_t13.py
```

Use these selections:

| GUI field | Value |
|---|---|
| DGIBI template | `source_codes\castem_tool.dgibi` |
| Working directory | a new directory outside tracked source, or `runs\baseline-example` |
| Cast3M version | `25` |
| `xrange` CSV | `examples\input\xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv` |
| `yrange` CSV | `examples\input\yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv` |
| `zfit_zmax` CSV | `examples\input\zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv` |
| `zfit_zmin` CSV | `examples\input\zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv` |

Use the matching naming parameters:

```text
re_ti      = 60
re_crpa    = 1
re_smfa    = 0.05
re_numspa  = 50
re_opmin   = 1e-6
```

For a first execution, use `nelem_x=1`, `nelem_y=1`, `nelem_z=1`, leave holes disabled, and leave MED/STL exports disabled. Uncheck **View mesh in Gmsh** if you want the solver to finish without launching another application. **Merge BDFs** may remain enabled.

Select **Run converter**. A successful run generates the canonical CSV copies, a patched DGIBI file, volume/boundary BDF files, and—when enabled—a combined BDF. Exact output names are documented in the main [README](../README.md#mesh-outputs).

## Output policy

The `output/` directory contains the generated DGIBI, a 2.74 MB combined BDF, and a sanitized run report selected from the real baseline execution. Separate meshes and solver traces are intentionally excluded because they duplicate the combined artifact, can be large, and may contain machine-specific paths. Re-run Cast3M locally, then compare the recorded parameters, card counts, file sizes, and checksums.

The recorded process returned `0` and Cast3M stopped at error level `0`, but the solver also emitted an `IEEE_INVALID_FLAG` notice. Treat the output as execution evidence only; no mesh-quality, numerical, or downstream CFD-import validation was performed.

Cast3M and a compatible `FISS` operator are external requirements. If they are unavailable, the GUI and static tests can still be launched, but mesh/flow results must not be inferred or fabricated.

## Run the documented multiple-hole example

From repo root, run:

```powershell
python scripts\run_multiple_holes_example.py
```

If `_runtime\multiple-holes-output` already exists from a prior run, rerun with:

```powershell
python scripts\run_multiple_holes_example.py --clean
```

## Run the accelerated multiple-hole path

The scientific bulk-hole implementation preserves the published baseline sources, creates all inflated radial rings in Python, writes three complete `CQUAD4` BDF surfaces, and removes the expensive Cast3M `REGL`/`INT_COMP`/`DISPLACE` hole pass. Use `castem_pipeline_gui_scientific.py` for interactive work; the script below is its non-interactive documented reproduction.

```powershell
python scripts\run_python_holes_example.py --clean
```

The script writes only ignored files under `_runtime\python-holes-output`. It reports the Cast3M return code, detected contour points, generated fill topology, radial fractions, preparation time, and whether `castem_mesh_v.bdf` was produced. The hole-ring angular count follows `nelem_x` and `nelem_y`, so the circular and square sides of every fill interface have the same number of edges. In the scientific GUI, use **Open generated mesh in Gmsh** on the Run / results tab to inspect an existing combined or volume BDF without rerunning Cast3M. For the method, real multi-size comparison, and element-orientation audit, see [the optimization note](../docs/python-hole-interpolation.md) and [provisional verification](../docs/provisional-verification.md).

## Run without the GUI

[`scientific-run.ini`](scientific-run.ini) contains the complete documented two-hole configuration, including mesh, export, merge, Gmsh, and FISS options. Validate or execute it from the repository root:

```powershell
python castem_pipeline_headless.py examples\scientific-run.ini --validate-only
python castem_pipeline_headless.py examples\scientific-run.ini
```

Relative paths are interpreted from the INI file. Edit `operation = mesh` to `fiss` or `both` when the optional FISS calculation is required.
