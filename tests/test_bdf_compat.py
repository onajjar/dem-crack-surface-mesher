from __future__ import annotations

from pathlib import Path

from bdf_compat import remove_degenerate_cquad4


def test_repeated_node_cquad4_is_removed_without_changing_valid_card(
    tmp_path: Path,
) -> None:
    mesh = tmp_path / "combined.bdf"
    mesh.write_text(
        "BEGIN BULK\n"
        "CQUAD4*               1               1              10              11\n"
        "*                     12              13\n"
        "CQUAD4*               3               1              30              31\n"
        "*                     32              32\n"
        "CQUAD4*               2               1              20              21\n"
        "*                     21              20\n"
        "ENDDATA\n",
        encoding="utf-8",
    )

    assert remove_degenerate_cquad4(mesh) == 1
    result = mesh.read_text(encoding="utf-8")
    assert "               1               1" in result
    assert "               3               1" in result
    assert "               2               1" not in result
    assert result.endswith("ENDDATA\n")


def test_unchanged_mesh_is_not_rewritten(tmp_path: Path) -> None:
    mesh = tmp_path / "combined.bdf"
    content = "BEGIN BULK\nCQUAD4,1,1,10,11,12,13\nENDDATA\n"
    mesh.write_text(content, encoding="utf-8")

    assert remove_degenerate_cquad4(mesh) == 0
    assert mesh.read_text(encoding="utf-8") == content
