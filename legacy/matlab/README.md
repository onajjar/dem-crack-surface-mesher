# Legacy MATLAB reference implementation

This directory preserves the original MATLAB surface-fitting implementation and
all MATLAB helper/post-processing files that accompanied it. They are retained
for provenance, scientific comparison, and historical reproducibility; the
current Python/Cast3M/Gmsh workflow does not invoke MATLAB.

The main program is `DEAP_crack_CFD_coupling.m`. The four
`DEAP_crack_CFD_coupling_post_process_*.m` files correspond to the bundled DEAP
application examples. Helper functions such as `build_fit_model.m`,
`TRIANgulation.m`, `surf2stl.m`, and `vtkwrite.m` are included unchanged from
the original source folder.

The repository's validation compares the Python result with archived CSVs from
this legacy workflow. It does not claim that MATLAB was rerun during automated
validation.

`SHA256SUMS` records every imported `.m` file. These hashes match the files in
the original `original_input/source` folder before publication.

Some archived post-processing scripts contain the original absolute example
paths. They are preserved intentionally and must be edited for a different
MATLAB workstation; the active Python workflow uses repository-relative paths.
