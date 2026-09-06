"""Deterministic pivoted QR for the MATLAB quadratic-LOESS compatibility path.

The six-column system is small but can be nearly singular. BLAS dispatch and
reduction order then affect surface values and contact decisions. This module
implements the reference-validated reduction, reflector, and triangular-solve
orders explicitly, without depending on a CPU vendor's LAPACK implementation.
See tests/data/matlab_r2025b for independent MATLAB inputs and expected results.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import math
import os
from functools import lru_cache

import numpy as np


@lru_cache(maxsize=1)
def _c_fma():
    """C99 fused multiply-add for Python 3.10-3.12 (math.fma starts at 3.13)."""
    library = ctypes.CDLL("ucrtbase" if os.name == "nt" else ctypes.util.find_library("m"))
    function = library.fma
    function.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double]
    function.restype = ctypes.c_double
    # Keep the library alive along with its function pointer.
    function._library = library
    return function


def _transpose_product(x: np.ndarray, y: np.ndarray, fused_tail: bool) -> float:
    """Reference transpose-matvec reduction, including its four-column tail.

    Each eight-row block makes four fused pairs, then adds them to four lanes.
    Complete groups of four output columns fuse the four-row remainder; the
    remaining output columns round those products before addition. The final
    one-to-three rows are fused in either case. These distinctions matter for
    ill-conditioned fits even though they describe the same real arithmetic.
    """
    accumulators = [0.0] * 4
    size = len(x)
    stop = size // 8 * 8
    fma = getattr(math, "fma", None) or _c_fma()
    for block in range(0, stop, 8):
        for lane in range(4):
            i = block + lane
            accumulators[lane] += fma(float(x[i]), float(y[i]), float(x[i + 4]) * float(y[i + 4]))
    four = stop + 4 if size - stop >= 4 else stop
    for i in range(stop, four):
        lane = i % 4
        if fused_tail:
            accumulators[lane] = fma(float(x[i]), float(y[i]), accumulators[lane])
        else:
            accumulators[lane] += float(x[i]) * float(y[i])
    for i in range(four, size):
        lane = i % 4
        accumulators[lane] = fma(float(x[i]), float(y[i]), accumulators[lane])
    return (accumulators[0] + accumulators[1]) + (accumulators[2] + accumulators[3])


def _round_extended_significand(value: int) -> int:
    """Round a nonnegative fixed-point integer to 64 significant binary bits."""
    shift = value.bit_length() - 64
    if shift <= 0:
        return value
    high = value >> shift
    remainder = value - (high << shift)
    halfway = 1 << (shift - 1)
    if remainder > halfway or (remainder == halfway and high % 2):
        high += 1
    return high << shift


def _reference_norm(values: np.ndarray) -> float:
    """Emulate the reference norm's four extended-precision accumulators.

    IEEE extended precision has a 64-bit significand. Python integers retain
    exact products, then implement round-to-nearest/even after each product,
    addition, and square root. This avoids platform-dependent ``long double``
    widths and the rare double-rounding difference from ``math.hypot``.
    Inputs are finite binary64 numbers; integer scaling also avoids overflow
    or underflow when squaring them.
    """
    parts = []
    base_exponent = 0
    for value in values:
        numerator, denominator = float(value).as_integer_ratio()
        exponent = -2 * (denominator.bit_length() - 1)
        parts.append((numerator * numerator, exponent))
        base_exponent = min(base_exponent, exponent)
    accumulators = [0] * 4
    for i, (square, exponent) in enumerate(parts):
        product = _round_extended_significand(square) << (exponent - base_exponent)
        lane = i % 4
        accumulators[lane] = _round_extended_significand(accumulators[lane] + product)
    total = 0
    for accumulator in accumulators:
        total = _round_extended_significand(total + accumulator)
    if total == 0:
        return 0.0
    # Normalize the square root to a 64-bit integer significand. Compare the
    # exact squared midpoint to round without an approximate floating root.
    exponent = (total.bit_length() - 1) // 2
    shift = 63 - exponent
    numerator = total << max(0, 2 * shift)
    denominator = 1 << max(0, -2 * shift)
    root = math.isqrt(numerator // denominator)
    midpoint_difference = 4 * numerator - denominator * (2 * root + 1) ** 2
    if midpoint_difference > 0 or (midpoint_difference == 0 and root % 2):
        root += 1
    final_exponent = exponent - 63 + base_exponent // 2
    # Hex parsing rounds directly to binary64, including subnormal results.
    return float.fromhex(f"0x{root:x}p{final_exponent:+d}")


def _pivoted_qr(a: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Unblocked Householder QR, modifying a private copy of the design."""
    m, n = a.shape
    pivot = np.arange(n)
    norms = np.array([_reference_norm(a[:, j]) for j in range(n)])
    exact_norms = norms.copy()
    tau = np.zeros(n)
    norm_threshold = math.sqrt(np.finfo(float).eps)
    fma = getattr(math, "fma", None) or _c_fma()
    for i in range(n):
        selected = i + int(np.argmax(norms[i:]))
        a[:, [i, selected]] = a[:, [selected, i]]
        pivot[[i, selected]] = pivot[[selected, i]]
        norms[[i, selected]] = norms[[selected, i]]
        exact_norms[[i, selected]] = exact_norms[[selected, i]]
        alpha = float(a[i, i])
        tail_norm = _reference_norm(a[i + 1:, i])
        if tail_norm != 0.0:
            large, small = max(abs(alpha), tail_norm), min(abs(alpha), tail_norm)
            beta = -math.copysign(large * math.sqrt(1.0 + (small / large) ** 2), alpha)
            tau[i] = (beta - alpha) / beta
            a[i + 1:, i] *= 1.0 / (alpha - beta)
            a[i, i] = beta
        if tau[i] != 0.0:
            diagonal = a[i, i]
            a[i, i] = 1.0
            # The QR reflector trims trailing zero rows/columns. Applying Q^T
            # to the response below deliberately retains its full row extent.
            last_row = i + int(np.flatnonzero(a[i:, i])[-1]) + 1
            last_column = n
            while last_column > i + 1 and not np.any(a[i:last_row, last_column - 1]):
                last_column -= 1
            fused_columns = (last_column - i - 1) // 4 * 4
            for j in range(i + 1, last_column):
                product = _transpose_product(a[i:last_row, i], a[i:last_row, j], j - i - 1 < fused_columns)
                scale = float(tau[i] * product)
                for row in range(i, last_row):
                    a[row, j] = fma(-float(a[row, i]), scale, float(a[row, j]))
            a[i, i] = diagonal
        # LAPACK's partial-norm downdate and recomputation threshold determine
        # pivot selection; always recomputing a norm changes rank decisions.
        for j in range(i + 1, n):
            if norms[j] != 0.0:
                ratio = abs(a[i, j]) / norms[j]
                remaining = max(0.0, (1.0 + ratio) * (1.0 - ratio))
                accuracy = remaining * (norms[j] / exact_norms[j]) ** 2
                if accuracy <= norm_threshold:
                    norms[j] = _reference_norm(a[i + 1:, j])
                    exact_norms[j] = norms[j]
                else:
                    norms[j] *= math.sqrt(remaining)
    return pivot, tau


def matlab_mldivide(design: np.ndarray, response: np.ndarray) -> np.ndarray:
    """Return the MATLAB-compatible basic solution of an m-by-6 local fit."""
    a = np.array(design, dtype=np.float64, copy=True)
    b = np.array(response, dtype=np.float64, copy=True)
    if a.ndim != 2 or a.shape[1] != 6 or a.shape[0] < 6:
        raise ValueError("MATLAB quadratic fitting requires an m-by-6 matrix, m >= 6.")
    m, n = a.shape
    if b.shape != (m,):
        raise ValueError("The fitting response must have one value per matrix row.")
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("The fitting matrix and response must be finite.")
    pivot, tau = _pivoted_qr(a)
    fma = getattr(math, "fma", None) or _c_fma()
    for i in range(n):
        if tau[i] == 0.0:
            continue
        product = _transpose_product(a[i + 1:, i], b[i + 1:], False) + b[i]
        scale = float(tau[i] * product)
        # The implicit leading 1 uses tau*product without intermediate rounding.
        b[i] = fma(-float(tau[i]), float(product), float(b[i]))
        for row in range(i + 1, m):
            b[row] = fma(-float(a[row, i]), scale, float(b[row]))
    tolerance = max(m, n) * np.finfo(float).eps * abs(a[0, 0])
    rank = int(np.count_nonzero(np.abs(np.diag(a[:n])) > tolerance))
    for i in range(rank - 1, -1, -1):
        b[i] /= a[i, i]
        for j in range(i):
            b[j] = fma(-float(b[i]), float(a[j, i]), float(b[j]))
    coefficients = np.zeros(n)
    coefficients[pivot[:rank]] = b[:rank]
    return coefficients


def backend_info() -> dict[str, str]:
    return {"name": "deterministic six-column pivoted QR", "version": "1",
            "fma": "math.fma" if hasattr(math, "fma") else "C99 fma",
            "reference": "MATLAB R2025b Update 1 / PCWIN64"}
