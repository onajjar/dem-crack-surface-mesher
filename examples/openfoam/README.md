# OpenFOAM case export example

This example meshes the bundled 50 × 50 crack with two circular holes and
inlet/outlet chambers using the source-free `python_only` backend, then writes
an OpenFOAM case next to the mesh. It needs neither Cast3M nor Gmsh; OpenFOAM
is needed only to run the case.

From the repository root, on Linux:

```bash
./run_linux.sh --headless examples/openfoam/run.ini --validate-only
./run_linux.sh --headless examples/openfoam/run.ini
```

or on Windows:

```powershell
python.exe .\castem_pipeline_gui_scientific.py --headless .\examples\openfoam\run.ini --validate-only
python.exe .\castem_pipeline_gui_scientific.py --headless .\examples\openfoam\run.ini
```

The working directory `_runtime/openfoam-example/` receives the usual BDF mesh
family and `openfoam_case/`:

```text
openfoam_case/
├── 0/                     U and p
├── constant/polyMesh/     points, faces, owner, neighbour, boundary, cellZones, faceZones
├── constant/              transport (both distributions' file names)
├── system/                controlDict, fvSchemes, fvSolution
├── Allrun, Allclean
├── openfoam_case.foam     opens the case in ParaView
└── openfoam_export.json   settings, patches, zones, quality report, warnings
```

Run it inside an OpenFOAM.com environment (on Windows, in WSL or Docker):

```bash
cd _runtime/openfoam-example/openfoam_case
./Allrun
```

For OpenFOAM.org 11 or later, set `openfoam_version = org` (the case then calls
`foamRun`). For a compressible case set `solver = rhoSimpleFoam`; pressures are
absolute in both cases.

The patches are `inlet` and `outlet` (the remote chamber faces), `lowerWall`,
`upperWall`, `sideWalls`, `hole1`, `hole2`, `inletChamberWalls` and
`outletChamberWalls`. The cell zones `crack`, `inletChamber` and
`outletChamber` and the face zones `crackInlet` and `crackOutlet` separate the
crack from the chambers; `postProcessing/` records the flow rate through the
two patches and the two crack mouths.

The export logs a size-jump warning: near the crack mouths, where the crack
almost closes, its thin layers touch much thicker chamber cells. The case is
written to stay stable there (see the
[OpenFOAM export guide](../../docs/openfoam-export.md)); more chamber height
elements reduce the jump.

The run measured on 2026-10-30 is listed in the guide's verification table.
