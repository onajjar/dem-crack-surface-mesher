# Project-specific Codex instructions

- Use local `git status`, `git diff`, explicit `git add`, `git commit`, and
  `git push` for publication in this repository.
- Do not use GitHub CLI (`gh`) or require a pull-request workflow unless the
  user explicitly changes this instruction.
- Preserve the immutable baseline files listed in `BASELINE_SHA256SUMS` and
  verify them before publication.
- Keep generated simulation and mesh outputs out of Git unless they are
  deliberately reviewed example artifacts. Large reviewed DEAP HDF5 examples
  must use the repository's Git LFS rules.
