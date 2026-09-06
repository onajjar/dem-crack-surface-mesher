# MATLAB/Python converter review

The published converter did not reproduce the broader MATLAB surface/contact
matrix. The corrected fitting implementation now passes the complete 216-case
local comparison. Native platform results are recorded separately in the CI
summary and numerical artifacts; they must be read with their commit hashes.

| Finding | Evidence | Correction |
| --- | --- | --- |
| P1: extraction/fitting differs from MATLAB | Released code matched 26/32 DEAP outcomes and 17/26 available surfaces at 1e-12 m; 538 contact points differed. | Correct time indexing, minimum eight neighbours, normalization, grid arithmetic, pivoted-QR basic solution and six-term evaluation. |
| P1: library/CPU arithmetic changes surfaces | Standard OpenBLAS changed two synthetic contact decisions. Explicit oneMKL still differed on AMD runners. | Implement the small QR system with explicit reduction, fused-operation and extended-norm rounding rules; remove the vendor BLAS requirement. |
| P2: span zero rejected by preflight | The corrected fitter accepts MATLAB's eight-neighbour span-zero case; the pipeline rejected it. | Accept zero span in headless validation. |
| P2: contact meshing failure occurs after validation | Python-only HEXA8 cannot represent a zero-aperture cell, but preflight accepted it. | Apply the same aperture restriction during preflight; retain the reconstructed contact geometry. |
| P2: upstream notice missing | The fdlibm power translation lacked its required permission notice. | Preserve the upstream copyright and permission notice. |

## Numerical contract

The lower and upper raw surfaces are fitted independently. Negative raw aperture
is set to zero; the lower wall is retained and the final upper wall is rebuilt
as lower + clamped aperture. Outside the data bounding rectangle the lower wall
is extended in the MATLAB order and the aperture is zero. Contact decisions use
the final stored wall values, with no extra tolerance or positive minimum gap.

The frozen reference is Windows MATLAB R2025b Update 1 / Curve Fitting Toolbox
25.2. A fresh run reproduced the August oracle. The two additional norm-rounding
regressions were also confirmed directly in MATLAB. Reference inputs, outputs,
checksums and the reproduction driver are committed with the converter.

The real-data set covers 32 scenarios across four DEAP applications, including
six expected no-surface outcomes. The arbitrary set covers ten point-cloud
families, four seeds and four spans (0.08, 0.20, 0.50, 1.00). The paired-wall set
covers constant gap, central touch, closed islands, closed stripes, checker
contact and rough contact at those four spans. Unit tests add zero span,
constant predictors, minimum sample count, rank handling and contact preflight.

All 216 local cases pass at the unchanged absolute tolerance of 1e-12 (metres
for real DEAP surfaces; input units for synthetic fixtures). Maximum differences
are 8.881784197001252e-16 m for real surfaces, 1.1102230246251565e-16 for arbitrary
predictions and 7.632783294297951e-17 for paired-wall arrays. Contact masks agree
at every tested point, including all 40,344 paired-wall grid decisions.

The Windows checkout passes 141 local tests. The Linux checkout passes 150 tests
on the Windows host with two platform-specific skips. Native CI provides the
separate Linux execution evidence. Both branches retain all 21 protected hashes:
six baseline runtime files and 15 legacy MATLAB files. Platform launchers and
the Linux BDF normalization remain intact.

## Practical limits

The Python-only HEXA8 mesher still requires strictly positive aperture. Contact
surfaces can be fitted, exported and characterized, but that mesher cannot create
a valid volume mesh through a closed patch. It now reports this before execution.

S05 is deliberately a low-threshold stress setting: MATLAB itself produces
unphysical elevations approaching 1.08e8 m. Reproducing that unstable fit is a
compatibility result, not validation of those settings for CFD. Inspect physical
geometry and fitting sensitivity before using a reconstructed domain.

These tests establish agreement for the stated reference release, inputs and
runtimes. They do not prove equivalence for every possible input, hardware
architecture, MATLAB release, or downstream CFD problem.

## Native validation

Both platform versions passed all five GitHub Actions jobs: Windows and Linux
with Python 3.10 and 3.13, plus the Docker build and execution checks. Each
version passed 184 fitting/contact cases on every matrix runtime and 32 further
DEAP cases on native Linux. Every saved report has the same three fitting-source
hashes as the complete local 216-case run. No contact decisions differ.

- [windows source 1e8bad0](https://github.com/onajjar/dem-crack-surface-mesher/actions/runs/34061077569): all five jobs passed.
- [linux source 64463a2](https://github.com/onajjar/dem-crack-surface-mesher/actions/runs/34061093981): all five jobs passed.
