from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from deap_crack_surface import (
    SurfaceConfig,
    _matlab_dot6,
    _matlab_linspace,
    _matlab_mean_std,
    _matlab_mldivide,
    _matlab_power3,
    extract_components,
    quadratic_loess_surface,
)

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_RESULTS = ROOT / "examples" / "deap" / "1_simple" / "results"


def test_surface_config_rejects_matlab_invalid_zero_time_step() -> None:
    config = SurfaceConfig(case_dir=SIMPLE_RESULTS, time_step=0)

    with pytest.raises(ValueError, match="time_step must be positive"):
        config.validate()


def test_time_one_uses_matlab_leading_time_zero_crack_count() -> None:
    config = SurfaceConfig(
        case_dir=SIMPLE_RESULTS,
        time_step=1,
        component=1,
        span=0.15,
        grid_resolution=20,
        opening_threshold=1.0e-5,
        orientation="XY",
    )

    assert extract_components(config) == []


def test_quadratic_loess_uses_matlab_minimum_eight_neighbors() -> None:
    x = np.array([0.00, 1.00, 0.00, 1.00, 0.20, 0.80, 0.15, 0.90])
    y = np.array([0.00, 0.00, 1.00, 1.00, 0.75, 0.20, 0.35, 0.65])
    z = np.array([0.10, 1.30, -0.20, 0.70, 1.90, -0.80, 0.55, 1.10])
    weights = np.array([1.00, 0.70, 1.30, 0.90, 1.80, 0.60, 1.10, 1.40])
    query_x = np.array([0.35, 0.62])
    query_y = np.array([0.45, 0.28])
    matlab_r2025b = np.array([1.9462267079463031, -1.7772539329725123])

    actual = quadratic_loess_surface(
        x,
        y,
        z,
        query_x,
        query_y,
        span=0.0,
        user_weights=weights,
    )

    np.testing.assert_allclose(actual, matlab_r2025b, rtol=0.0, atol=1.0e-12)


def test_quadratic_loess_rejects_fewer_than_eight_points_like_matlab() -> None:
    x = np.array([0.0, 1.0, 0.0, 1.0, 0.2, 0.8, 0.4])
    y = np.array([0.0, 0.0, 1.0, 1.0, 0.7, 0.2, 0.5])
    z = np.array([0.1, 1.3, -0.2, 0.7, 1.9, -0.8, 0.4])

    with pytest.raises(ValueError, match="at least eight points"):
        quadratic_loess_surface(
            x,
            y,
            z,
            np.array([0.35]),
            np.array([0.45]),
            span=0.2,
        )


def test_tricube_power_uses_matlab_fdlibm_rounding() -> None:
    values = np.array(
        [
            0.2567675499409164,
            0.6660719568983523,
            0.9196634671711154,
            0.4912915266547040,
        ]
    )
    matlab_r2025b = np.array(
        [
            float.fromhex("0x1.155b9763e36e0p-6"),
            float.fromhex("0x1.2e989d941b4d6p-2"),
            float.fromhex("0x1.8e403af5ac3b6p-1"),
            float.fromhex("0x1.e5b5f7abe0a18p-4"),
        ]
    )

    actual = _matlab_power3(values)

    assert np.array_equal(actual, matlab_r2025b)


def test_normalization_uses_matlab_short_vector_reduction() -> None:
    rng = np.random.default_rng(20260825 + 37 * len("near_collinear"))
    x = np.linspace(-1.0, 1.0, 36) + rng.normal(0.0, 2.0e-4, 36)
    y = 0.75 * x + rng.normal(0.0, 1.0e-5, 36)
    matlab_r2025b = np.array(
        [
            float.fromhex("-0x1.c3527ece3c71cp-16"),
            float.fromhex("0x1.343ba7ece3738p-1"),
            float.fromhex("-0x1.57d85eebcc38ep-16"),
            float.fromhex("0x1.ce59048aca4bbp-2"),
        ]
    )

    actual = np.array([*_matlab_mean_std(x), *_matlab_mean_std(y)])

    assert np.array_equal(actual, matlab_r2025b)


def test_grid_uses_matlab_linspace_rounding() -> None:
    matlab_r2025b = np.arange(30, dtype=np.float64) / np.float64(29.0)
    matlab_r2025b[-1] = 1.0

    actual = _matlab_linspace(0.0, 1.0, 30)

    assert np.array_equal(actual, matlab_r2025b)


def test_mldivide_applies_qr_reflectors_like_matlab() -> None:
    design = np.array(
        [
            [0.9268697120273693, 0.17644682366478684, 2.1933976862402758, 0.03358992226997384, 5.190582179539526, 0.41755389106873875],
            [0.9038147069548795, 0.1370276879048891, 2.138838910799162, 0.020774819338602615, 5.061470953223735, 0.32427017229589256],
            [0.49253893251094244, 0.6061656580028739, 1.1655723498113166, 0.7460056062347801, 2.758277189822942, 1.4344651432354254],
            [0.3005038340794762, 0.3998698368946048, 0.7111295238247272, 0.5320926667971536, 1.682857728602012, 0.9462749371361608],
            [0.3005038340794762, 0.3998698368946048, 0.7111295238247272, 0.5320926667971536, 1.682857728602012, 0.9462749371361608],
            [0.00892999807759148, 0.011580055789560536, 0.014315791993332402, 0.015016542100477374, 0.022949825813583513, 0.018564132770703276],
            [0.004116720661901152, 0.0005934929442023151, 0.005351989686136418, 8.556176232158206e-05, 0.0069579152808688614, 0.0007715772764379504],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        ]
    )
    response = np.array(
        [
            0.48400861973725656,
            0.6749339811973545,
            0.2538486291023314,
            0.14841932633124993,
            0.14841932633124993,
            0.004457034248806394,
            0.003097359277052727,
            0.0,
        ]
    )
    matlab_r2025b = np.array(
        [
            -4896196.778026137,
            -1019969.0009724444,
            5948233.268584909,
            1.1777445957872903,
            -1639258.0896335563,
            431010.1656831974,
        ]
    )

    actual = _matlab_mldivide(design, response)

    assert np.array_equal(actual, matlab_r2025b)


def test_six_term_evaluation_uses_matlab_pairwise_tree() -> None:
    terms = np.array(
        [
            1.0,
            0.5246890048393152,
            2.215487023416543,
            0.275298551799271,
            4.908382750927093,
            1.1624416815508427,
        ]
    )
    coefficients = np.array(
        [
            -4896196.780152076,
            -1019969.0015194645,
            5948233.271775069,
            1.1777445975744327,
            -1639258.0905127227,
            431010.1659143515,
        ]
    )

    actual = _matlab_dot6(terms, coefficients)

    assert actual == 201788.6958179539


def test_zero_bandwidth_duplicate_neighborhood_matches_matlab_nan() -> None:
    x = np.r_[np.zeros(8), 1.0, 0.0, 1.0, -1.0]
    y = np.r_[np.zeros(8), 0.0, 1.0, 1.0, -1.0]
    z = np.r_[np.linspace(0.1, 0.8, 8), 1.2, -0.3, 0.7, 0.4]

    actual = quadratic_loess_surface(
        x,
        y,
        z,
        np.array([0.0, 0.1]),
        np.array([0.0, 0.1]),
        span=0.0,
    )

    np.testing.assert_array_equal(actual, np.array([np.nan, 0.0]))


def test_constant_predictor_is_treated_as_unscaled_like_matlab() -> None:
    y = np.array(
        [
            -1.0,
            -0.8181818181818182,
            -0.6363636363636364,
            -0.4545454545454546,
            -0.2727272727272727,
            -0.09090909090909091,
            0.09090909090909091,
            0.2727272727272727,
            0.4545454545454546,
            0.6363636363636364,
            0.8181818181818182,
            1.0,
        ]
    )
    z = np.array(
        [
            -0.8414709848078965,
            -0.7299042197100739,
            -0.5942747875482894,
            -0.4390539679535607,
            -0.2693589075355986,
            -0.09078392350887036,
            0.09078392350887036,
            0.2693589075355986,
            0.4390539679535607,
            0.5942747875482894,
            0.7299042197100739,
            0.8414709848078965,
        ]
    )

    actual = quadratic_loess_surface(
        np.ones(12),
        y,
        z,
        np.ones(2),
        np.array([-0.2, 0.4]),
        span=0.5,
    )

    np.testing.assert_array_equal(
        actual, np.array([-0.19851857769185016, 0.389289905483917])
    )


def test_rank_deficient_loess_uses_matlab_basic_qr_solution() -> None:
    x = np.linspace(-1.0, 1.0, 12)
    y = 2.0 * x + 0.25
    z = np.sin(2.3 * x) + 0.2 * x * x
    weights = np.linspace(0.5, 1.7, 12)
    query_x = np.array([-0.40, 0.10, 0.55])
    query_y = np.array([-0.55, 0.45, 1.15])
    matlab_r2025b = np.array(
        [-0.7539535318668750, 0.2345310924032311, 0.9997516878304804]
    )

    actual = quadratic_loess_surface(
        x,
        y,
        z,
        query_x,
        query_y,
        span=0.20,
        user_weights=weights,
    )

    np.testing.assert_allclose(actual, matlab_r2025b, rtol=0.0, atol=1.0e-12)
