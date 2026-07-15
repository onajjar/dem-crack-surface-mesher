from __future__ import annotations

from pathlib import PurePosixPath

from scripts.verify_baseline import (
    DEFAULT_MANIFEST,
    REPOSITORY_ROOT,
    read_manifest,
    verify_entries,
)

EXPECTED_BASELINE_SHA256 = {
    PurePosixPath("bpm_cfx.ico"): (
        "a906a62b5e698885bb7271784818fd75b816e389c79d27ccfbb69af7d1ca68c1"
    ),
    PurePosixPath("castem_pipeline_gui_t13.py"): (
        "7610c790c689ebaab40756f369b68a11930b50f11c11773857b103d22bb6fe82"
    ),
    PurePosixPath("source_codes/castem_tool.dgibi"): (
        "97f458ec43a423e2a65cf2e474e537fde97e61168e12c5fd67f9b7fdc0f2ea36"
    ),
    PurePosixPath("source_codes/fiss.eso"): (
        "05f215afd73c20ef516e5fe2a7f561c37d9ef8e9f899b336c3b84fa6f7b16807"
    ),
    PurePosixPath("source_codes/fuite_fissure.dgibi"): (
        "b3d38b25eaf701fff60072f922b346e50b7a819da6e869b8540e6ee1eee33191"
    ),
    PurePosixPath("source_codes/merge_surface_bdf.py"): (
        "83b65655b26d28c7bcabda1a503df1d15e1b49d1819cea2cf15b003158e7dbd3"
    ),
}


def test_manifest_covers_the_immutable_baseline() -> None:
    entries = read_manifest(DEFAULT_MANIFEST)
    assert {
        entry.relative_path: entry.digest for entry in entries
    } == EXPECTED_BASELINE_SHA256


def test_immutable_baseline_files_match_recorded_hashes() -> None:
    entries = read_manifest(DEFAULT_MANIFEST)
    assert verify_entries(entries, REPOSITORY_ROOT) == ()
