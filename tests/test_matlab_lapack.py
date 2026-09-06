import numpy as np
import pytest

import matlab_lapack


def test_missing_reference_backend_does_not_silently_fall_back(monkeypatch):
    matlab_lapack._backend.cache_clear()
    monkeypatch.setattr(matlab_lapack, "_library_candidates", lambda: [])
    try:
        with pytest.raises(RuntimeError, match="not substituted"):
            matlab_lapack.matlab_mldivide(np.ones((8, 6)), np.ones(8))
    finally:
        matlab_lapack._backend.cache_clear()


@pytest.mark.parametrize("design,response", [
    (np.ones((8, 5)), np.ones(8)),
    (np.ones((8, 6)), np.ones((8, 1))),
    (np.full((8, 6), np.nan), np.ones(8)),
])
def test_backend_rejects_invalid_arrays_before_entering_native_code(design, response):
    with pytest.raises(ValueError):
        matlab_lapack.matlab_mldivide(design, response)


def test_native_solver_does_not_mutate_callers_arrays():
    rng = np.random.default_rng(503)
    a = rng.normal(size=(12, 6))
    expected = np.arange(6, dtype=float)
    b = a @ expected
    aa, bb = a.copy(), b.copy()
    actual = matlab_lapack.matlab_mldivide(a, b)
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-12)
    np.testing.assert_array_equal(a, aa)
    np.testing.assert_array_equal(b, bb)
