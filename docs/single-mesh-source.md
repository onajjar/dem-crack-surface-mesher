# Single Cast3M mesh source

## Scope

The repository maintains one Cast3M source for crack-volume meshing:
`source_codes/castem_tool.dgibi`. Ordinary meshes, meshes with Python-generated
hole fills, and meshes with inlet/outlet chambers all use this same file.

`source_codes/fuite_fissure.dgibi` is intentionally separate because it runs
the optional FISS flow calculation rather than the mesh converter.
`source_codes/fiss.eso` is operator source and is not a mesh program.

## Native chamber option

The complete chamber construction is implemented directly in
`castem_tool.dgibi`. Its Main Program contains:

```text
opti_chamb = 0 ;
```

- `0` follows the normal crack-only branch.
- `1` creates inlet and outlet chambers and exports their named volumes and
  boundaries.

The geometry and exports are guarded by native Cast3M conditions:

```text
SI (NON (EGA opti_chamb 0)) ;
    * chamber construction or chamber-only exports
FINSI ;
```

The source always exports `vo_export`: it refers to `vo_cr` when chambers are
disabled and `vo_all` when they are enabled. MED output and the optional
Cast3M visualization use the same selected volume.

## Python boundary

Python does not contain or inject Cast3M chamber geometry. The
`chamber_geometry.py` module only:

1. validates dimensions, element counts, and grading ratios;
2. sets `opti_chamb` to `0` or `1`;
3. patches the eleven scalar assignments in the generated run copy; and
4. declares the expected BDF/STL filenames for output verification.

The separate Python hole optimizer may still replace the historical
hole-interpolation block in the generated run copy. That optimization is
independent of the chamber geometry already present in the Cast3M source.

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
controlled by `[chambers] enabled`, which maps directly to `opti_chamb`.

## Integrity and verification

The mesh source was intentionally extended to satisfy the native-source
requirement; its earlier byte-preserved version remains available in Git
history. `BASELINE_SHA256SUMS` now records the authoritative current runtime
digest. Run:

```powershell
python.exe .\scripts\verify_baseline.py
python.exe -m pytest
python.exe -m ruff check .
```

The chamber tests assert that:

- the repository has one `castem_tool*.dgibi` file;
- Cast3M owns the chamber `VOLU` construction and guarded exports;
- Python contains no chamber construction/export program strings;
- enabled and disabled configurations patch `opti_chamb` to `1` and `0`; and
- every named chamber boundary remains part of the expected output manifest.
