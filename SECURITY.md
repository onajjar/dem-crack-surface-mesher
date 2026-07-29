# Security Policy

## Supported version

Security fixes are considered for the latest published baseline and the default branch. Older snapshots may not receive updates.

| Version | Supported |
|---|---|
| `0.1.0-baseline` | Yes |
| Earlier repository history | No |

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting or security-advisory feature for this repository. If the private reporting button is unavailable, contact the maintainer through their GitHub profile to request a private channel without including vulnerability details. Do not disclose an unpatched vulnerability in a public issue, discussion, pull request, screenshot, or solver log.

Include:

- the affected file and version or commit;
- a concise description of the impact;
- reproduction steps or a minimal proof of concept;
- relevant platform, Python, Cast3M, and Gmsh versions;
- whether untrusted CSV, DGIBI, BDF, HDF5, or path input is involved; and
- any proposed mitigation, if known.

Do not include real credentials, confidential geometry, or unnecessarily large solver output. A maintainer will acknowledge the report when it has been reviewed and coordinate disclosure based on severity and available validation resources; no fixed response-time guarantee is made.

## Scope and operational safety

The application launches local Cast3M templates and may open generated meshes in Gmsh. Treat templates and result files from untrusted sources as potentially unsafe, use a dedicated working directory, and review generated commands and paths before execution. This baseline does not sandbox Cast3M, Gmsh, Python, DGIBI templates, or post-processing files.
