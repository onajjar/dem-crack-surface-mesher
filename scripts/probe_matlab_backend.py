"""Diagnostic only: identify CPU-dispatch effects on two frozen MATLAB probes."""
from __future__ import annotations

import ctypes
import json
import os
import platform
import runpy
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def child():
    import matlab_lapack
    tests = runpy.run_path(str(ROOT / "tests/test_matlab_fitting_compatibility.py"))
    result = {"cpu": platform.processor(), "mode": os.environ.get("MKL_CBWR", "AUTO"),
              "backend": matlab_lapack.backend_info(), "tests": {}}
    lib = matlab_lapack._backend().lib
    lib.MKL_CBWR_Get_Auto_Branch.argtypes = []
    lib.MKL_CBWR_Get_Auto_Branch.restype = ctypes.c_int
    result["auto_branch"] = lib.MKL_CBWR_Get_Auto_Branch()
    for name in ("test_mldivide_applies_qr_reflectors_like_matlab",
                 "test_constant_predictor_is_treated_as_unscaled_like_matlab"):
        try:
            tests[name]()
            result["tests"][name] = "PASS"
        except AssertionError as error:
            result["tests"][name] = "FAIL " + str(error)
    print(json.dumps(result))


def main():
    rows = []
    for mode in ("AUTO", "COMPATIBLE", "SSE2", "SSE4_2", "AVX", "AVX2", "AVX2,STRICT",
                 "AVX512", "AVX512_E1"):
        env = dict(os.environ, MKL_CBWR=mode, MKL_NUM_THREADS="1", MKL_DYNAMIC="FALSE")
        process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child"],
                                 env=env, text=True, capture_output=True, timeout=60)
        rows.append({"mode": mode, "returncode": process.returncode,
                     "stdout": process.stdout, "stderr": process.stderr})
        print(mode, process.stdout.strip(), process.stderr.strip(), flush=True)
    destination = ROOT / "_runtime/backend-probe.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    child() if "--child" in sys.argv else main()
