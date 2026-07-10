# Immutable source audit

Audit date: 2026-07-10

This document records the read-only audit used to select the publishable baseline. The original project directory was not edited. All publication work occurred in a separate Git clone.

## Inventory and tree

The original tree contains **1,398,551 files** totaling **35,939,645,325 bytes (33.47 GiB)**. A literal million-line tree would not be useful; the complete recursion was therefore summarized by top-level entry and extension, while the current executable source tree is listed exactly.

```text
original project/
├── root files                         39 files      374,267,787 B
├── .vscode/                            1 file               174 B
├── Brazilian/                         21 files       55,517,265 B
├── calcul_complet_fiss/          872,342 files   30,211,068,812 B
├── COBRA/                               4 files          184,837 B
├── fast/                          443,510 files    1,305,613,636 B
├── fiss/                            4,044 files      117,084,237 B
├── POISEU_BLASIUS/                     4 files          435,874 B
├── sans_castem/                        14 files       25,390,913 B
├── source_codes/                        4 files           66,893 B
├── work1/                          67,132 files    1,005,092,490 B
├── work11/                             17 files      141,216,687 B
├── work111/                            16 files       89,582,902 B
├── work12/                          7,835 files      524,101,086 B
├── work22/                          3,552 files      448,656,722 B
├── work55/                             16 files    1,641,365,010 B
└── worknn/                              0 files                0 B
```

Most of the tree is generated simulation data:

| Extension | Files | Bytes |
|---|---:|---:|
| `.txt` | 1,397,921 | 30,725,989,833 |
| `.bdf` | 96 | 4,686,101,324 |
| `.med` | 3 | 255,823,977 |
| `.h5` | 9 | 109,380,106 |
| `.pdf` | 286 | 78,019,245 |
| `.stl` | 23 | 71,395,421 |
| `.csv` | 112 | 10,447,213 |
| `.trace` | 26 | 678,701 |
| `.ps` | 26 | 0 |

The exact current source selected for the baseline is:

```text
.
├── castem_pipeline_gui_t13.py        117,944 B
├── bpm_cfx.ico                       137,676 B
└── source_codes/
    ├── castem_tool.dgibi              21,738 B
    ├── fiss.eso                       16,718 B
    ├── fuite_fissure.dgibi            26,054 B
    └── merge_surface_bdf.py            2,383 B
```

Historical GUI variants (`castem_pipeline_gui.py`, T2 through T12, and T11-old), experiment directories, and generated results are not runtime dependencies of T13 and were not imported.

## Byte-preservation manifest

| File | Newlines | SHA-256 |
|---|---|---|
| `castem_pipeline_gui_t13.py` | CRLF | `7610c790c689ebaab40756f369b68a11930b50f11c11773857b103d22bb6fe82` |
| `bpm_cfx.ico` | binary | `a906a62b5e698885bb7271784818fd75b816e389c79d27ccfbb69af7d1ca68c1` |
| `source_codes/castem_tool.dgibi` | LF | `97f458ec43a423e2a65cf2e474e537fde97e61168e12c5fd67f9b7fdc0f2ea36` |
| `source_codes/fiss.eso` | LF | `05f215afd73c20ef516e5fe2a7f561c37d9ef8e9f899b336c3b84fa6f7b16807` |
| `source_codes/fuite_fissure.dgibi` | CRLF | `b3d38b25eaf701fff60072f922b346e50b7a819da6e869b8540e6ee1eee33191` |
| `source_codes/merge_surface_bdf.py` | LF | `83b65655b26d28c7bcabda1a503df1d15e1b49d1819cea2cf15b003158e7dbd3` |

`.gitattributes`, `BASELINE_SHA256SUMS`, `scripts/verify_baseline.py`, and CI protect these bytes, including their original newline styles.

## Dependencies

The GUI imports standard-library modules plus:

- NumPy and Matplotlib at import time;
- Tkinter/Tcl-Tk for the interface; and
- h5py optionally for FISS TXT-to-HDF5 conversion.

Python 3.10 or newer is required by the source syntax. Cast3M is required for meshing and FISS. Gmsh is optional and is launched only for visualization. The baseline resolves a `CASTEM_PATH` override before its version-derived Windows installation layout, then runs Cast3M using `cmd.exe /c`. It resolves Gmsh from `GMSH_PATH`, standard installation locations, matching home-directory folders, or `PATH`.

## CSV contract

T13 selects four CSV matrices:

- x coordinates (`xrange`);
- y coordinates (`yrange`);
- upper z surface (`zfit_zmax`); and
- lower z surface (`zfit_zmin`).

Both supplied DGIBI templates read comma-separated matrices without headers. They calculate the mean surface and opening pointwise. Across the 112 CSV copies in the original tree, all files were finite numeric matrices and all complete quartets had equal shapes. There were only two unique datasets: `50 × 50` and `50 × 110`. The GUI itself checks only file existence; equal shape, minimum `2 × 2` size, finite values, and upper/lower ordering remain user responsibilities.

The included example is the smallest existing complete quartet (`50 × 50`, 184,837 B total). It is unmodified and documented in `examples/README.md`. Its scientific provenance was not documented in the supplied tree, so it is presented only as a baseline execution input.

## Pipeline and outputs

The mesh path:

1. reads GUI paths and parameters;
2. copies the four inputs under Cast3M-compatible names;
3. patches only the marked DGIBI Main Program;
4. writes a generated DGIBI file;
5. runs Cast3M asynchronously in the selected working directory;
6. produces volume, upper/lower/mean, side, and optional hole-surface meshes;
7. optionally exports MED/STL;
8. optionally merges CQUAD4 boundary cards with the volume BDF; and
9. optionally opens the selected BDF in Gmsh.

The FISS path is separate. It copies the same CSV geometry into a model-specific calculation directory, patches a FISS DGIBI template, calls the Cast3M `FISS` operator for geometry-line/pressure/temperature combinations, exports geometry and result text series, and offers plot/HDF5 post-processing.

## Security and sensitive-data review

No likely credentials, API tokens, private-key headers, credentialed URLs, email addresses, or actual user-home paths were found in the immutable baseline files. A wider scan of source/configuration-like files and sensitive filenames also found no credential material.

One generated Cast3M trace contained a personal absolute path. That trace and all other traces were excluded. The source contains only generic installation defaults and placeholders.

Because generated `.txt` results account for more than 30 GiB and nearly 1.4 million files, their full content scan was stopped after the relevant structural and source/configuration checks. No claim is made that every generated numeric payload was content-scanned. Those result trees were excluded rather than published.

## Exclusion rationale

The baseline excludes editor settings, historical experiments, run directories, traces, PostScript, large BDF/MED/STL meshes, HDF5 stores, plot PDFs, quarantined FISS text, caches, and environments. This prevents personal paths, machine-specific state, and more than 33 GiB of generated material from entering Git.

No `LICENSE` file existed. In addition, the provenance/redistribution terms of `source_codes/fiss.eso` were not documented. These are release-governance issues, not reasons to alter the preserved bytes; they are called out explicitly in the main README.
