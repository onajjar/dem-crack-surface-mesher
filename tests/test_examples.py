from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIRECTORY = REPOSITORY_ROOT / "examples" / "input"

CSV_FILES = {
    "xrange": "xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
    "yrange": "yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
    "zmax": "zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv",
    "zmin": "zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv",
}

EXPECTED_INPUT_SHA256 = {
    "xrange": "e921f1c90d704df8e981ccb85a75b2ac2a50ec742a193341064cc1e3d04c7a09",
    "yrange": "89f2f63aa4707b761582a4a15ff8709071ebcec87332ee27ac2437c837f9a682",
    "zmax": "cb2fb2db6d2d8e6af00da6f34a98cb521a3e23c4b9fda6ecba0022f9c36c55c5",
    "zmin": "6b38423281dad212107b29630271760169b49610f43ba30f0cf9b33c4c6417b4",
}

EXPECTED_HOLES = [
    {"cx": -0.2, "cy": 0.2, "r": 0.07},
    {"cx": 0.2, "cy": -0.2, "r": 0.07},
]

EXPECTED_REPORT_ARTIFACTS = {
    "examples/output/run-report.json": {
        "castem_tool_ti60_crpa1_smfa5_numsp50_opmin1.dgibi",
        "combined_ti60_crpa1_smfa5_numsp50_opmin1.bdf",
    },
    "examples/multiple-holes/output/run-report.json": {
        "examples/multiple-holes/output/castem_tool_ti60_crpa1_smfa5_numsp50_opmin1.dgibi",
        "examples/multiple-holes/output/combined_ti60_crpa1_smfa5_numsp50_opmin1.bdf",
        "docs/assets/multiple-holes-mesh-preview.png",
    },
}

SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        document = json.load(stream)
    assert isinstance(document, dict), f"expected a JSON object in {path}"
    return document


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_published_artifact(report_path: Path, raw_path: str) -> Path:
    assert "\\" not in raw_path, f"artifact path is not portable: {raw_path!r}"
    relative_path = PurePosixPath(raw_path)
    assert not relative_path.is_absolute(), f"absolute artifact path: {raw_path!r}"
    assert relative_path.parts and all(
        part not in {"", ".", ".."} for part in relative_path.parts
    ), f"unsafe artifact path: {raw_path!r}"

    if len(relative_path.parts) == 1:
        candidate = report_path.parent.joinpath(*relative_path.parts)
    else:
        candidate = REPOSITORY_ROOT.joinpath(*relative_path.parts)

    resolved_root = REPOSITORY_ROOT.resolve()
    resolved_candidate = candidate.resolve(strict=False)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise AssertionError(f"artifact leaves repository: {raw_path!r}") from exc
    return candidate


def test_shared_csv_quartet_is_finite_and_geometrically_consistent() -> None:
    matrices = {
        name: np.loadtxt(INPUT_DIRECTORY / filename, delimiter=",")
        for name, filename in CSV_FILES.items()
    }

    assert {matrix.shape for matrix in matrices.values()} == {(50, 50)}
    for name, matrix in matrices.items():
        assert np.isfinite(matrix).all(), f"{CSV_FILES[name]} contains non-finite data"
        assert _sha256(INPUT_DIRECTORY / CSV_FILES[name]) == EXPECTED_INPUT_SHA256[name]

    assert np.greater_equal(matrices["zmax"], matrices["zmin"]).all(), (
        "zfit_zmax must be greater than or equal to zfit_zmin at every grid point"
    )


def test_multiple_holes_parameters_contain_the_documented_holes() -> None:
    document = _read_json(
        REPOSITORY_ROOT / "examples" / "multiple-holes" / "parameters.json"
    )
    parameters = document["parameters"]

    assert parameters["holes_enabled"] is True
    assert parameters["holes"] == EXPECTED_HOLES
    for hole in parameters["holes"]:
        assert all(
            isinstance(hole[key], (int, float))
            and not isinstance(hole[key], bool)
            and math.isfinite(hole[key])
            for key in ("cx", "cy", "r")
        )
        assert hole["r"] > 0


def test_published_run_report_artifacts_match_recorded_integrity_data() -> None:
    for relative_report, expected_paths in EXPECTED_REPORT_ARTIFACTS.items():
        report_path = REPOSITORY_ROOT.joinpath(*PurePosixPath(relative_report).parts)
        report = _read_json(report_path)
        published = report["published_artifacts"]
        assert isinstance(published, list), f"invalid artifact list in {relative_report}"

        records_by_path = {record["path"]: record for record in published}
        assert len(records_by_path) == len(published), (
            f"duplicate published artifact path in {relative_report}"
        )
        assert set(records_by_path) == expected_paths

        for raw_path, record in records_by_path.items():
            recorded_size = record["bytes"]
            recorded_sha256 = record["sha256"]
            assert (
                isinstance(recorded_size, int)
                and not isinstance(recorded_size, bool)
                and recorded_size >= 0
            ), f"invalid byte size for {raw_path}"
            assert (
                isinstance(recorded_sha256, str)
                and SHA256_PATTERN.fullmatch(recorded_sha256) is not None
            ), f"invalid SHA-256 for {raw_path}"

            artifact_path = _resolve_published_artifact(report_path, raw_path)
            assert artifact_path.is_file(), f"missing published artifact: {raw_path}"
            assert artifact_path.stat().st_size == recorded_size, (
                f"byte-size mismatch for {raw_path}"
            )
            assert _sha256(artifact_path) == recorded_sha256, (
                f"SHA-256 mismatch for {raw_path}"
            )

        combined_records = [
            record
            for path, record in records_by_path.items()
            if PurePosixPath(path).name.startswith("combined_")
            and PurePosixPath(path).suffix == ".bdf"
        ]
        assert len(combined_records) == 1
        combined_summary = report["combined_bdf_summary"]
        assert combined_summary["bytes"] == combined_records[0]["bytes"]
        assert combined_summary["sha256"] == combined_records[0]["sha256"]
