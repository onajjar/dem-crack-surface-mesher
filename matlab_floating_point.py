"""Floating-point kernels needed for MATLAB-compatible crack fitting.

MATLAB R2025b evaluates the two powers in its tricube LOWESS weight with
fdlibm semantics.  Platform ``pow`` implementations can differ by one ULP,
which materially changes rank-deficient local fits.  The specialization below
is a vectorized translation of the freely distributable fdlibm 5.3 ``pow``
algorithm for finite non-negative inputs and exponent 3.  fdlibm originated at
Sun Microsystems. Original source: https://www.netlib.org/fdlibm/e_pow.c

Copyright (C) 2004 by Sun Microsystems, Inc. All rights reserved.

Permission to use, copy, modify, and distribute this
software is freely granted, provided that this notice
is preserved.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]

_LOW_MASK = np.uint64(0xFFFF_FFFF)
_HIGH_MASK = np.uint64(0xFFFF_FFFF_0000_0000)

_CP = float.fromhex("0x1.ec709dc3a03fdp-1")
_CP_H = float.fromhex("0x1.ec709ep-1")
_CP_L = -float.fromhex("0x1.e2fe0145b01f5p-28")
_DP_H = float.fromhex("0x1.2b8034p-1")
_DP_L = float.fromhex("0x1.cfdeb43cfd006p-27")
_L1 = float.fromhex("0x1.3333333333303p-1")
_L2 = float.fromhex("0x1.b6db6db6fabffp-2")
_L3 = float.fromhex("0x1.55555518f264dp-2")
_L4 = float.fromhex("0x1.17460a91d4101p-2")
_L5 = float.fromhex("0x1.d864a93c9db65p-3")
_L6 = float.fromhex("0x1.a7e284a454eefp-3")
_P1 = float.fromhex("0x1.555555555553ep-3")
_P2 = -float.fromhex("0x1.6c16c16bebd93p-9")
_P3 = float.fromhex("0x1.1566aaf25de2cp-14")
_P4 = -float.fromhex("0x1.bbd41c5d26bf1p-20")
_P5 = float.fromhex("0x1.6376972bea4d0p-25")
_LG2 = float.fromhex("0x1.62e42fefa39efp-1")
_LG2_H = float.fromhex("0x1.62e43p-1")
_LG2_L = -float.fromhex("0x1.05c610ca86c39p-29")


def _high_word(values: FloatArray) -> NDArray[np.uint32]:
    return (values.view(np.uint64) >> np.uint64(32)).astype(np.uint32)


def _low_word(values: FloatArray) -> NDArray[np.uint32]:
    return (values.view(np.uint64) & _LOW_MASK).astype(np.uint32)


def _with_low_word(values: FloatArray, low: int = 0) -> FloatArray:
    bits = values.view(np.uint64).copy()
    bits &= _HIGH_MASK
    bits |= np.uint64(low)
    return bits.view(np.float64)


def _with_high_word(values: FloatArray, high: NDArray[np.integer]) -> FloatArray:
    bits = values.view(np.uint64).copy()
    bits &= _LOW_MASK
    bits |= high.astype(np.uint64) << np.uint64(32)
    return bits.view(np.float64)


def matlab_power3(values: FloatArray) -> FloatArray:
    """Return fdlibm ``pow(x, 3.0)`` for finite non-negative doubles.

    This intentionally does not simplify the operation to ``x*x*x``.  MATLAB's
    general array-power kernel and a correctly rounded cube can differ by one
    ULP.  Keeping each operation as a separate NumPy ufunc also prevents
    contraction from changing fdlibm's prescribed rounding sequence.
    """
    original_shape = np.asarray(values).shape
    x_abs = np.asarray(values, dtype=np.float64).reshape(-1).copy()
    if np.any(~np.isfinite(x_abs)) or np.any(x_abs < 0.0):
        raise ValueError("MATLAB power-to-three input must be finite and non-negative")
    result = np.empty_like(x_abs)
    special = (x_abs == 0.0) | (x_abs == 1.0)
    result[special] = x_abs[special]
    active = ~special
    if not np.any(active):
        return result.reshape(original_shape)

    x = x_abs[active]
    ix = _high_word(x).astype(np.int64)
    n = np.zeros(x.size, dtype=np.int64)
    subnormal = ix < 0x0010_0000
    if np.any(subnormal):
        x[subnormal] *= float.fromhex("0x1.0p53")
        n[subnormal] -= 53
        ix[subnormal] = _high_word(x[subnormal]).astype(np.int64)
    n += (ix >> 20) - 0x3FF
    j = ix & 0x000F_FFFF
    normalized_high = j | 0x3FF0_0000
    k = np.zeros(x.size, dtype=np.int64)
    middle = (j > 0x3988E) & (j < 0xBB67A)
    upper = j >= 0xBB67A
    k[middle] = 1
    n[upper] += 1
    normalized_high[upper] -= 0x0010_0000
    x = _with_high_word(x, normalized_high)

    bp = 1.0 + 0.5 * k
    u = x - bp
    v = 1.0 / (x + bp)
    ss = u * v
    s_h = _with_low_word(ss)
    t_h_word = ((normalized_high >> 1) | 0x2000_0000) + 0x0008_0000 + (k << 18)
    t_h = _with_high_word(np.zeros_like(x), t_h_word)
    t_l = x - (t_h - bp)
    s_l = v * ((u - s_h * t_h) - s_h * t_l)
    s2 = ss * ss
    r = s2 * s2 * (
        _L1 + s2 * (_L2 + s2 * (_L3 + s2 * (_L4 + s2 * (_L5 + s2 * _L6))))
    )
    r = r + s_l * (s_h + ss)
    s2 = s_h * s_h
    t_h = 3.0 + s2 + r
    t_h = _with_low_word(t_h)
    t_l = r - ((t_h - 3.0) - s2)
    u = s_h * t_h
    v = s_l * t_h + t_l * ss
    p_h = u + v
    p_h = _with_low_word(p_h)
    p_l = v - (p_h - u)
    z_h = _CP_H * p_h
    z_l = _CP_L * p_h + p_l * _CP + _DP_L * k
    t = n.astype(np.float64)
    t1 = ((z_h + z_l) + _DP_H * k) + t
    t1 = _with_low_word(t1)
    t2 = z_l - (((t1 - t) - _DP_H * k) - z_h)

    # y is exactly 3.0, but retain fdlibm's split multiplication sequence.
    y = 3.0
    y1 = _with_low_word(np.full_like(x, y))
    p_l = (y - y1) * t1 + y * t2
    p_h = y1 * t1
    z = p_l + p_h
    z_high_unsigned = _high_word(z)
    z_high = z_high_unsigned.view(np.int32).astype(np.int64)
    z_low = _low_word(z).astype(np.int64)
    if np.any(z_high >= 0x4090_0000):
        raise OverflowError("unexpected overflow in MATLAB power-to-three kernel")
    underflow = (
        z_high_unsigned.astype(np.int64) & 0x7FFF_FFFF
    ) >= 0x4090_CC00
    definitely_underflow = underflow & (
        ((z_high - np.int64(-0x3F6F_3400)) | z_low) != 0
    )
    result_active = np.empty_like(x)
    result_active[definitely_underflow] = 0.0
    calculate = ~definitely_underflow

    ph = p_h[calculate].copy()
    pl = p_l[calculate]
    zz = z[calculate]
    j_signed = z_high[calculate]
    j_unsigned = z_high_unsigned[calculate].astype(np.int64)
    magnitude = j_unsigned & 0x7FFF_FFFF
    exponent = (magnitude >> 20) - 0x3FF
    n_scale = np.zeros(zz.size, dtype=np.int64)
    reduce = magnitude > 0x3FE0_0000
    if np.any(reduce):
        shift = exponent[reduce] + 1
        n_word = j_signed[reduce] + (0x0010_0000 >> shift)
        n_word_unsigned = n_word & 0xFFFF_FFFF
        exponent_reduced = ((n_word_unsigned & 0x7FFF_FFFF) >> 20) - 0x3FF
        clear_mask = ~(0x000F_FFFF >> exponent_reduced) & 0xFFFF_FFFF
        t_high = n_word_unsigned & clear_mask
        truncated = _with_high_word(
            np.zeros(np.count_nonzero(reduce), dtype=np.float64), t_high
        )
        n_value = ((n_word_unsigned & 0x000F_FFFF) | 0x0010_0000) >> (
            20 - exponent_reduced
        )
        n_value[j_signed[reduce] < 0] *= -1
        n_scale[reduce] = n_value
        ph[reduce] -= truncated
    tt = pl + ph
    tt = _with_low_word(tt)
    u = tt * _LG2_H
    v = (pl - (tt - ph)) * _LG2 + tt * _LG2_L
    zz = u + v
    w = v - (zz - u)
    tt = zz * zz
    t1 = zz - tt * (
        _P1 + tt * (_P2 + tt * (_P3 + tt * (_P4 + tt * _P5)))
    )
    r = (zz * t1) / (t1 - 2.0) - (w + zz * w)
    zz = 1.0 - (r - zz)
    output_high = _high_word(zz).astype(np.int64) + (n_scale << 20)
    subnormal_output = (output_high >> 20) <= 0
    if np.any(subnormal_output):
        zz[subnormal_output] = np.ldexp(zz[subnormal_output], n_scale[subnormal_output])
    normal_output = ~subnormal_output
    if np.any(normal_output):
        zz[normal_output] = _with_high_word(
            zz[normal_output], output_high[normal_output]
        )
    result_active[calculate] = zz
    result[active] = result_active
    return result.reshape(original_shape)
