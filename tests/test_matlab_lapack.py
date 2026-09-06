import numpy as np
import pytest

import matlab_lapack


def test_c99_fma_preserves_rounding_needed_on_python_before_313():
    x, y = 1.0 + 2.0**-27, 1.0 - 2.0**-27
    assert x * y - 1.0 == 0.0
    assert matlab_lapack._c_fma()(x, y, -1.0) == -2.0**-54


def test_norm_retains_reference_extended_precision_rounding():
    # The exact norm lies just above a binary64 midpoint. Rounding its square
    # root to an extended (64-bit) significand first yields the midpoint, which
    # then rounds to even. Direct binary64 hypot would produce 1 + 2**-52.
    values = np.array([1.0, 2.0**-26, 2.0**-52])
    assert matlab_lapack._reference_norm(values) == 1.0


def test_zero_rank_returns_basic_zero_solution():
    np.testing.assert_array_equal(
        matlab_lapack.matlab_mldivide(np.zeros((8, 6)), np.ones(8)), np.zeros(6)
    )


@pytest.mark.parametrize("design,response", [
    (np.ones((8, 5)), np.ones(8)),
    (np.ones((8, 6)), np.ones((8, 1))),
    (np.full((8, 6), np.nan), np.ones(8)),
])
def test_solver_rejects_invalid_arrays(design, response):
    with pytest.raises(ValueError):
        matlab_lapack.matlab_mldivide(design, response)


def test_solver_does_not_mutate_callers_arrays():
    rng = np.random.default_rng(503)
    a = rng.normal(size=(12, 6))
    expected = np.arange(6, dtype=float)
    b = a @ expected
    aa, bb = a.copy(), b.copy()
    actual = matlab_lapack.matlab_mldivide(a, b)
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-12)
    np.testing.assert_array_equal(a, aa)
    np.testing.assert_array_equal(b, bb)
