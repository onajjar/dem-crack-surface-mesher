from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOI = "10.1016/j.nucengdes.2025.114718"
TITLE = (
    "Three-dimensional crack reconstruction from Beam–Particle Model for "
    "CFD-based leakage assessment"
)
FAMILY_NAMES = (
    "Najjar",
    "Heitz",
    "Oliver-Leblond",
    "Tailhan",
    "Rastiello",
    "Ragueneau",
)


def test_repository_citation_files_identify_the_preferred_article() -> None:
    cff = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    bibtex = (ROOT / "CITATION.bib").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "cff-version: 1.2.0" in cff
    assert "preferred-citation:" in cff
    assert TITLE in cff.replace("\n    ", " ")
    assert f'doi: "{DOI}"' in cff
    assert "journal: \"Nuclear Engineering and Design\"" in cff
    assert "volume: 448" in cff
    assert "start: 114718" in cff
    assert "year: 2026" in cff
    assert all(cff.count(f"family-names: {name}") == 2 for name in FAMILY_NAMES)

    assert "@article{Najjar2026CrackReconstruction" in bibtex
    assert f"doi     = {{{DOI}}}" in bibtex
    assert "pages   = {114718}" in bibtex
    assert DOI in readme
    assert "[`CITATION.cff`](CITATION.cff)" in readme
    assert "[`CITATION.bib`](CITATION.bib)" in readme
