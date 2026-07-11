# Scientific Workbench

`castem_pipeline_gui_scientific.py` is the single launcher for the enhanced workflow. It adds a clearer scientific interface and the accelerated bulk-hole implementation without editing the immutable T13 GUI or its Cast3M templates.

## Workflow

1. Open the workbench and select **Load documented example** to load the complete repository-relative two-hole configuration, or select the DGIBI template, a dedicated working directory, and the four structured CSV grids yourself.
2. Use **Validate inputs** to check that the matrices are finite, equally shaped, and satisfy `zfit_zmax >= zfit_zmin`.
3. Use **Preview XY geometry** to inspect the real source grid and configured hole circles before a run.
4. In **Mesh & holes**, choose one mode:
   - **Original T13 hole workflow — reference** preserves the original Cast3M construction, interpolation, and displacement behavior.
   - **Bulk Python hole mesh — fast + inflated** vectorizes the common interpolation path, writes complete lower/upper/mean `CQUAD4` fill meshes, and lets Cast3M read them with `LIRE 'NAS'`.
5. Set `num_el_fill` for the radial cell count and `re_fact_hole` for the outermost-to-hole-adjacent width ratio.
6. In **Run & results**, validate again and launch Cast3M. The live solver log and run state are streamed without blocking the interface.

The no-hole path remains the preserved baseline regardless of the selected hole mode. The previous `castem_pipeline_gui_python_holes.py` entry point is retained only as a compatibility wrapper and redirects to this workbench.

Changing a tracked path or parameter marks the validation state as stale. Mesh and FISS launches are mutually exclusive, and both buttons remain disabled until the active process finishes. Before a mesh run, prior fixed-name solver artifacts in the selected directory are moved to `_previous_mesh_runs`; after return code `0`, the workbench checks the expected volume and surface files before declaring the run verified.

## Inflation behavior

The bulk mode constructs every radial ring explicitly before writing the BDF. The live normalized profile in the hole panel previews those cell edges. With `num_el_fill=5` and `re_fact_hole=5`, it produces five cells whose widths grow geometrically away from the hole, with a measured outermost/hole-adjacent ratio of `4.99999988` after Cast3M import in the documented test.

See [Bulk inflated hole meshing](python-hole-interpolation.md) for the algorithm and [Provisional verification](provisional-verification.md) for the real integration, orientation, and timing evidence.

## FISS

The **FISS flow** tab retains the same configured input variables and invokes the baseline FISS execution/post-processing methods. It is separated from the primary mesh workflow because it is a second Cast3M calculation, not a mesh-export option.

## Mesh comparison

The **Open mesh comparison** action opens `docs/assets/mesh-comparison-baseline-vs-python-holes.png` when it exists. Recreate it only from independent real reference and scientific BDF outputs:

```powershell
python scripts\benchmark_hole_optimization.py --clean
python -m pip install -r requirements-visuals.txt -c constraints-baseline.txt
python scripts\render_hole_mesh_comparison.py
```

To retain the already verified reference cases and rerun only the scientific cases:

```powershell
python scripts\benchmark_hole_optimization.py --reuse-baseline
python scripts\render_hole_mesh_comparison.py
```

The renderer reports exported BDF cell counts and visual geometry. It does not certify numerical equivalence, physical correctness, CFD compatibility, or general mesh quality.
