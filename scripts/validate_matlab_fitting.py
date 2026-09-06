"""Fail-fast, portable comparison to frozen MATLAB R2025b reference arrays."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

import numpy as np
import scipy
from scipy.io import loadmat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deap_crack_surface import (  # noqa: E402
    SurfaceConfig,
    quadratic_loess_surface,
    reconstruct_surface,
)
from matlab_lapack import backend_info  # noqa: E402

FIXTURES = ROOT / "tests/data/matlab_r2025b"
TOLERANCE = 1e-12


def array_metrics(actual: np.ndarray, expected: np.ndarray) -> dict:
    if actual.shape != expected.shape:
        return {"pass": False, "reason": "shape mismatch"}
    masks_match = all(np.array_equal(fn(actual), fn(expected))
                      for fn in (np.isnan, np.isposinf, np.isneginf))
    finite = np.isfinite(actual) & np.isfinite(expected)
    error = float(np.max(np.abs(actual[finite] - expected[finite]), initial=0))
    return {"pass": masks_match and error <= TOLERANCE,
            "max_abs_error": error, "nonfinite_masks_match": masks_match,
            "exact": bool(np.array_equal(actual, expected, equal_nan=True))}


def validate(groups: list[str], arrays_dir: Path | None = None) -> dict:
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    for relative, expected in provenance["files"].items():
        actual = hashlib.sha256((FIXTURES / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"MATLAB fixture checksum mismatch: {relative}")
    if arrays_dir:
        arrays_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for group in groups:
        if group == "deap":
            cases = json.loads((FIXTURES / "inputs/deap_scenarios.json").read_text())
            statuses = {c["id"]: c["status"] for c in json.loads(
                (FIXTURES / "expected/deap_status.json").read_text())}
            for relative, expected in provenance["deap_inputs"].items():
                if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
                    raise ValueError(f"DEAP input missing or changed: {relative}; run git lfs pull.")
            for case in cases:
                row = {"group": group, "id": case["id"], "pass": False}
                try:
                    kwargs = {k: v for k, v in case.items()
                              if k not in ("id", "source_case", "purpose")}
                    kwargs["case_dir"] = ROOT / "examples/deap" / case["source_case"] / "results"
                    result = reconstruct_surface(SurfaceConfig(**kwargs))
                except ValueError as error:
                    # Missing files, DLL/load errors and programming errors are
                    # infrastructure failures, never matching no-surface results.
                    message = str(error)
                    expected_failure = (message.startswith("no crack openings exceed ")
                                        or (message.startswith("component ")
                                            and "eligible components exist" in message))
                    row.update(status="no_surface", error=message,
                               **{"pass": expected_failure and statuses[case["id"]] == "error"})
                    rows.append(row)
                    continue
                row["status"] = "surface"
                if statuses[case["id"]] != "ok":
                    rows.append(row)
                    continue
                ref = loadmat(FIXTURES / "expected/deap" / (case["id"] + ".mat"))
                pairs = {"x": (result.x, ref["xrange_i"]),
                         "y": (result.y, ref["yrange_i"]),
                         "zmin": (result.z_min, ref["zfit_zmin_i"]),
                         "zmax": (result.z_max, ref["zfit_zmax_i"])}
                row["arrays"] = {k: array_metrics(*v) for k, v in pairs.items()}
                row["contact_mismatches"] = int(np.count_nonzero(
                    (result.z_max == result.z_min) != (ref["zfit_zmax_i"] == ref["zfit_zmin_i"])))
                row["negative_apertures"] = int(np.count_nonzero(result.z_max < result.z_min))
                row["pass"] = (all(v["pass"] for v in row["arrays"].values())
                               and row["contact_mismatches"] == row["negative_apertures"] == 0)
                if arrays_dir:
                    np.savez_compressed(arrays_dir / (case["id"] + ".npz"),
                                        **{k: v[0] for k, v in pairs.items()},
                                        **{"matlab_" + k: v[1] for k, v in pairs.items()})
                rows.append(row)
        else:
            data = loadmat(FIXTURES / "inputs" / (group + "_inputs.mat"), squeeze_me=True)
            ref = loadmat(FIXTURES / "expected" / ("matlab_" + group + "_outputs.mat"),
                          squeeze_me=True)
            for i, case_id in enumerate(data["case_ids"]):
                def fit(key):
                    return quadratic_loess_surface(
                        data["xs"][i], data["ys"][i], data[key][i], data["qxs"][i],
                        data["qys"][i], span=float(data["spans"][i]),
                        user_weights=data["weights"][i])

                if not ref["successes"][i]:
                    raise ValueError(f"Unexpected unsuccessful MATLAB fixture: {case_id}")
                row = {"group": group, "id": str(case_id)}
                if group == "arbitrary":
                    pairs = {"prediction": (fit("zs"), ref["predictions"][i])}
                else:
                    lower, upper = fit("zmins"), fit("zmaxs")
                    final = lower + np.maximum(upper - lower, 0)
                    pairs = {"lower": (lower, ref["raw_lowers"][i]),
                             "raw_upper": (upper, ref["raw_uppers"][i]),
                             "final_upper": (final, ref["final_uppers"][i])}
                    row["contact_mismatches"] = int(np.count_nonzero(
                        (final == lower) != (ref["final_uppers"][i] == ref["raw_lowers"][i])))
                    row["negative_apertures"] = int(np.count_nonzero(final < lower))
                row["arrays"] = {k: array_metrics(*v) for k, v in pairs.items()}
                row["pass"] = (all(v["pass"] for v in row["arrays"].values())
                               and row.get("contact_mismatches", 0) == 0
                               and row.get("negative_apertures", 0) == 0)
                if arrays_dir:
                    np.savez_compressed(arrays_dir / (str(case_id) + ".npz"),
                                        x=data["qxs"][i], y=data["qys"][i],
                                        **{k: v[0] for k, v in pairs.items()},
                                        **{"matlab_" + k: v[1] for k, v in pairs.items()})
                rows.append(row)
        print(f"{group}: {sum(r['pass'] for r in rows if r['group'] == group)}/"
              f"{sum(r['group'] == group for r in rows)} passed", flush=True)
    sources = ("deap_crack_surface.py", "matlab_floating_point.py", "matlab_lapack.py")
    return {"pass": all(r["pass"] for r in rows), "cases": rows,
            "absolute_tolerance": TOLERANCE, "backend": backend_info(),
            "runtime": {"platform": platform.platform(), "machine": platform.machine(),
                        "python": platform.python_version(), "numpy": np.__version__,
                        "scipy": scipy.__version__},
            "source_sha256": {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
                              for p in sources},
            "fixture_provenance_sha256": hashlib.sha256(
                (FIXTURES / "provenance.json").read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--groups", nargs="+", choices=("deap", "arbitrary", "contact"),
                        default=["deap", "arbitrary", "contact"])
    parser.add_argument("--output", type=Path, default=ROOT / "_runtime/matlab-validation.json")
    parser.add_argument("--arrays", type=Path)
    args = parser.parse_args()
    report = validate(args.groups, args.arrays)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"MATLAB validation: {'PASS' if report['pass'] else 'FAIL'} ({len(report['cases'])} cases)")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
