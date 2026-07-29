# Python-only HEXA8 chamber example

This example generates the same crack, two circular holes, graded Z layers,
and graded inlet/outlet chambers as the maintained Cast3M reference case, but
it uses only Python/NumPy for meshing. It does not read a mesh DGIBI, resolve a
Cast3M executable, or launch Gmsh.

From the repository root:

```powershell
python.exe .\castem_pipeline_gui_scientific.py --headless `
  .\examples\python-only-chambers\run.ini --validate-only

python.exe .\castem_pipeline_gui_scientific.py --headless `
  .\examples\python-only-chambers\run.ini
```

The working directory receives:

- `castem_mesh_v.bdf`, containing the complete HEXA8 volume;
- the same named crack, hole, chamber, and complete-exterior boundary BDFs as
  the Cast3M path;
- separate inlet and outlet volume BDFs;
- safe double-precision ASCII STL boundary files;
- the requested merged BDF;
- `python_mesh_preview.png`, generated without Gmsh;
- `headless-run-report.json`, including grading, element counts, mesh quality,
  dependencies, and timings.

The reference comparison and timing evidence are recorded in
[`validation-summary.json`](validation-summary.json) after running the
reproducible validator described in
[`docs/python-only-meshing.md`](../../docs/python-only-meshing.md). The
numbering-independent comparison matched all 830,579 referenced nodes, all
798,400 HEXA8, both 68,600-element chamber volumes, and all 24 boundary sets
in both topology and winding within a coordinate tolerance of $10^{-9}$. The
final measured mesh phase was 12.33 times faster than the reviewed Cast3M run
on the same host and case.
