# Single Cast3M mesh source

## Scope

The repository maintains one Cast3M source for crack-volume meshing:
`source_codes/castem_tool.dgibi`. Ordinary meshes, meshes with Python-generated
hole fills, and meshes with inlet/outlet chambers all begin from this same
byte-preserved file.

`source_codes/fuite_fissure.dgibi` is intentionally separate because it runs
the optional FISS flow calculation rather than the mesh converter.
`source_codes/fiss.eso` is operator source and is not a mesh program.

## How chamber runs are generated

The launcher never edits the maintained mesh source. It performs the following
operations in memory:

1. Patch the normal mesh, naming, hole, visualization, and export parameters.
2. When chambers are enabled, remove the unused node-by-node `DISPLACE`
   procedure from the generated copy.
3. Replace the historical hole-correction block with the three bulk NASTRAN
   readers used by the Python hole workflow.
4. Insert the validated inlet/outlet parameters and construction block before
   the normal export stage.
5. Redirect the main volume, MED, and visualization targets to the combined
   crack-and-chamber volume and add every named chamber boundary export.
6. Write the resulting DGIBI into the configured working directory and run
   Cast3M there.

The transformation is implemented in `chamber_geometry.py`. Its anchors are
validated strictly: a missing or repeated source marker raises an error instead
of producing a partially patched run file.

## Reproducible commands

Validate the complete chamber configuration without starting Cast3M:

```powershell
python.exe .\castem_pipeline_gui_scientific.py --headless `
  .\examples\chambers\run.ini --validate-only
```

Generate the chamber mesh:

```powershell
python.exe .\castem_pipeline_gui_scientific.py --headless `
  .\examples\chambers\run.ini
```

Run the ordinary chamber-disabled example:

```powershell
python.exe .\castem_pipeline_gui_scientific.py --headless `
  .\examples\scientific-run.ini
```

Both INI files point to `source_codes/castem_tool.dgibi`. Chamber behavior is
controlled only by `[chambers] enabled`.

## Preservation and verification

`BASELINE_SHA256SUMS` records the authoritative mesh-source digest. Run:

```powershell
python.exe .\scripts\verify_baseline.py
python.exe -m pytest
python.exe -m ruff check .
```

The chamber test suite also checks that the generated active Cast3M program
contains no `DISPLACE`, `DEPL`, `INT_COMP`, or legacy hole-fill `REGL`
operation, requires every named chamber BDF, and retains the single-source
marker.
