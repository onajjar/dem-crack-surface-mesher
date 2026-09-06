"""The LAPACK backend validated against the MATLAB R2025b fitting oracle.

SciPy wheels use different BLAS/LAPACK implementations. In nearly singular
quadratic fits, their rounding differences can change the reconstructed walls
and contact decisions materially. Use the same oneMKL implementation on both
platforms instead of silently selecting the host SciPy LAPACK.

Loaded lazily: CSV, synthetic surfaces, and meshing do not require oneMKL.
"""

from __future__ import annotations

import ctypes
import os
import sys
from functools import lru_cache
from importlib import metadata
from pathlib import Path

import numpy as np


def _library_candidates() -> list[Path]:
    names = ("mkl_rt.2.dll", "mkl_rt.dll") if os.name == "nt" else (
        "libmkl_rt.so.2", "libmkl_rt.so",
    )
    candidates: list[Path] = []
    try:
        distribution = metadata.distribution("mkl")
        for entry in distribution.files or ():
            if entry.name in names:
                candidates.append(Path(distribution.locate_file(entry)).resolve())
    except metadata.PackageNotFoundError:
        pass
    # Conda packages need not expose Python distribution metadata. Also allow
    # a venv to use the oneMKL runtime from its base Python installation.
    for prefix in dict.fromkeys((sys.prefix, sys.base_prefix)):
        for relative in ("Library/bin", "lib", "bin"):
            candidates.extend(Path(prefix) / relative / name for name in names)
    return list(dict.fromkeys(candidates))


class _MatlabLapack:
    def __init__(self, path: Path):
        if "ILP64" in os.environ.get("MKL_INTERFACE_LAYER", "").upper():
            raise RuntimeError("MATLAB-compatible fitting requires the oneMKL LP64 interface.")
        self._dll_directory = (
            os.add_dll_directory(str(path.parent)) if os.name == "nt" else None
        )
        self.lib = ctypes.CDLL(str(path))
        integer = ctypes.c_int
        character = ctypes.c_char
        doubles = np.ctypeslib.ndpointer(dtype=np.float64, flags="F_CONTIGUOUS")
        integers = np.ctypeslib.ndpointer(dtype=np.int32, flags="F_CONTIGUOUS")
        self.lib.LAPACKE_dgeqp3.argtypes = [
            integer, integer, integer, doubles, integer, integers, doubles,
        ]
        self.lib.LAPACKE_dormqr.argtypes = [
            integer, character, character, integer, integer, integer,
            doubles, integer, doubles, doubles, integer,
        ]
        self.lib.LAPACKE_dtrtrs.argtypes = [
            integer, character, character, character, integer, integer,
            doubles, integer, doubles, integer,
        ]
        for name in ("LAPACKE_dgeqp3", "LAPACKE_dormqr", "LAPACKE_dtrtrs"):
            getattr(self.lib, name).restype = integer
        self.lib.MKL_Get_Version_String.argtypes = [ctypes.c_char_p, integer]
        self.lib.MKL_Get_Version_String.restype = None
        version = ctypes.create_string_buffer(256)
        self.lib.MKL_Get_Version_String(version, len(version))
        self.version = version.value.decode("ascii", errors="replace")

    @staticmethod
    def _check(info: int, operation: str) -> None:
        if info != 0:
            raise np.linalg.LinAlgError(f"oneMKL {operation} failed with info={info}")

    def solve(self, design: np.ndarray, response: np.ndarray) -> np.ndarray:
        a = np.array(design, dtype=np.float64, order="F", copy=True)
        b = np.array(response, dtype=np.float64, copy=True)
        if a.ndim != 2 or a.shape[1] != 6 or a.shape[0] < 6:
            raise ValueError("MATLAB quadratic fitting requires an m-by-6 matrix, m >= 6.")
        m, n = a.shape
        if b.shape != (m,):
            raise ValueError("The fitting response must have one value per matrix row.")
        if not np.isfinite(a).all() or not np.isfinite(b).all():
            raise ValueError("The fitting matrix and response must be finite.")
        pivot = np.zeros(n, dtype=np.int32)
        tau = np.zeros(n, dtype=np.float64)
        self._check(self.lib.LAPACKE_dgeqp3(102, m, n, a, m, pivot, tau), "DGEQP3")
        b = np.asfortranarray(b[:, None])
        self._check(
            self.lib.LAPACKE_dormqr(102, b"L", b"T", m, 1, n, a, m, tau, b, m),
            "DORMQR",
        )
        r = np.array(np.triu(a[:n, :]), order="F")
        tolerance = max(m, n) * np.finfo(np.float64).eps * abs(r[0, 0])
        rank = int(np.count_nonzero(np.abs(np.diag(r)) > tolerance))
        coefficients = np.zeros(n, dtype=np.float64)
        if rank:
            rr = np.array(r[:rank, :rank], order="F", copy=True)
            bb = np.array(b[:rank], order="F", copy=True)
            self._check(
                self.lib.LAPACKE_dtrtrs(102, b"U", b"N", b"N", rank, 1,
                                        rr, rank, bb, rank),
                "DTRTRS",
            )
            coefficients[pivot[:rank] - 1] = bb[:, 0]
        return coefficients


@lru_cache(maxsize=1)
def _backend() -> _MatlabLapack:
    errors = []
    for path in _library_candidates():
        if path.is_file():
            try:
                return _MatlabLapack(path)
            except (OSError, AttributeError) as error:
                errors.append(str(error))
    detail = " " + "; ".join(errors) if errors else ""
    raise RuntimeError(
        "MATLAB-compatible DEAP fitting requires oneMKL on Windows/Linux x86-64. "
        "Install requirements.txt (mkl==2023.1.0), then rerun the MATLAB fixture tests. "
        "The SciPy backend is not substituted because it can change contact surfaces."
        + detail
    )


def matlab_mldivide(design: np.ndarray, response: np.ndarray) -> np.ndarray:
    """Pivoted-QR basic solution with the reference backend's reduction order."""
    return _backend().solve(design, response)


def backend_info() -> dict[str, str]:
    return {"name": "oneMKL LAPACKE", "version": _backend().version,
            "reference": "MATLAB R2025b Update 1 / PCWIN64"}
