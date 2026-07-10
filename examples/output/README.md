# Verified example outputs

These files were produced on 2026-07-10 by driving the unchanged `castem_pipeline_gui_t13.App._run` path with the CSV quartet in `../input` and Cast3M annual version 2025.0 (launcher version `25`).

The process returned `0`, Cast3M stopped at error level `0`, and the GUI completed its integrated BDF merge. Cast3M also reported a signalling `IEEE_INVALID_FLAG` after its normal stop. The files demonstrate reproducible execution; they are **not** a mesh-quality, CFX-import, or numerical validation.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `castem_tool_ti60_crpa1_smfa5_numsp50_opmin1.dgibi` | 22,280 | `bd44c5507730f9e4b62dfd2fe3e5dee402ad40e9317320eeddc057321a573237` |
| `combined_ti60_crpa1_smfa5_numsp50_opmin1.bdf` | 2,742,398 | `67151e7608887c6a65ad93118bc4867e961f1bdd32712ff37658d7b66cf7304b` |
| `run-report.json` | 3,536 | sanitized execution record |

The combined BDF contains 15,000 `GRID`, 4,802 `CHEXA`, 5,194 `CQUAD4`, and 6 `PSHELL` cards. The mean surface is excluded by the unchanged integrated merger.

See `run-report.json` for versions, parameters, timings, notices, omitted-output checksums, and the exact validation boundary. Separate volume/surface BDFs, solver trace/PostScript files, and copied inputs were omitted to avoid duplication and machine-specific paths.
