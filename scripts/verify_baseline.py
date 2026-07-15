"""Verify that the published baseline files retain their original bytes."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "BASELINE_SHA256SUMS"
MANIFEST_LINE = re.compile(
    r"^(?P<digest>[0-9a-fA-F]{64})[ \t]+(?:\*)?(?P<path>\S(?:.*\S)?)$"
)


class ManifestError(ValueError):
    """Raised when the checksum manifest is malformed or unsafe."""


@dataclass(frozen=True)
class BaselineEntry:
    digest: str
    relative_path: PurePosixPath

    @property
    def display_path(self) -> str:
        return self.relative_path.as_posix()


def _validated_relative_path(raw_path: str, line_number: int) -> PurePosixPath:
    if "\\" in raw_path:
        raise ManifestError(
            f"line {line_number}: paths must use forward slashes: {raw_path!r}"
        )

    relative_path = PurePosixPath(raw_path)
    if (
        relative_path.is_absolute()
        or not relative_path.parts
        or any(part in {"", ".", ".."} for part in relative_path.parts)
    ):
        raise ManifestError(
            f"line {line_number}: path must stay within the repository: {raw_path!r}"
        )
    return relative_path


def read_manifest(manifest_path: Path = DEFAULT_MANIFEST) -> tuple[BaselineEntry, ...]:
    """Read a sha256sum-style manifest without changing repository contents."""

    try:
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {manifest_path}: {exc}") from exc

    entries: list[BaselineEntry] = []
    seen_paths: set[PurePosixPath] = set()
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        match = MANIFEST_LINE.fullmatch(line)
        if match is None:
            raise ManifestError(f"line {line_number}: invalid SHA-256 entry")

        relative_path = _validated_relative_path(match.group("path"), line_number)
        if relative_path in seen_paths:
            raise ManifestError(
                f"line {line_number}: duplicate path {relative_path.as_posix()!r}"
            )
        seen_paths.add(relative_path)
        entries.append(
            BaselineEntry(match.group("digest").lower(), relative_path)
        )

    if not entries:
        raise ManifestError("manifest contains no checksum entries")
    return tuple(entries)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return a file's SHA-256 digest using bounded memory."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_entries(
    entries: Iterable[BaselineEntry], repository_root: Path = REPOSITORY_ROOT
) -> tuple[str, ...]:
    """Return human-readable failures for missing, unsafe, or changed files."""

    root = repository_root.resolve()
    failures: list[str] = []
    for entry in entries:
        candidate = root.joinpath(*entry.relative_path.parts)
        resolved_candidate = candidate.resolve(strict=False)
        try:
            resolved_candidate.relative_to(root)
        except ValueError:
            failures.append(f"unsafe path: {entry.display_path}")
            continue

        if not candidate.is_file():
            failures.append(f"missing file: {entry.display_path}")
            continue

        try:
            actual = sha256_file(candidate)
        except OSError as exc:
            failures.append(f"cannot read {entry.display_path}: {exc}")
            continue

        if actual != entry.digest:
            failures.append(
                f"checksum mismatch: {entry.display_path}\n"
                f"  expected: {entry.digest}\n"
                f"  actual:   {actual}"
            )

    return tuple(failures)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify immutable baseline files against BASELINE_SHA256SUMS."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="repository root (default: inferred from this script)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="checksum manifest (default: <root>/BASELINE_SHA256SUMS)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    manifest = args.manifest or root / "BASELINE_SHA256SUMS"

    try:
        entries = read_manifest(manifest)
    except ManifestError as exc:
        print(f"Baseline verification failed: {exc}", file=sys.stderr)
        return 2

    failures = verify_entries(entries, root)
    if failures:
        print("Baseline verification failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(f"Baseline verification passed: {len(entries)} files match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
