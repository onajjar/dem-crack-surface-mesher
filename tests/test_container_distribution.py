from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_container_distribution_is_complete_and_non_privileged() -> None:
    required = (
        ".dockerignore",
        "Dockerfile",
        "compose.yaml",
        "container-output/README.md",
        "docs/docker.md",
        "examples/docker/README.md",
        "examples/docker/constant-planes.ini",
    )
    for relative_path in required:
        assert (ROOT / relative_path).is_file(), relative_path

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "docker.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    example = (ROOT / "examples" / "docker" / "constant-planes.ini").read_text(
        encoding="utf-8"
    )

    assert "FROM python:3.11-slim-bookworm" in dockerfile
    assert "libtk8.6" in dockerfile
    assert 'python -c "import tkinter; print(tkinter.TkVersion)"' in dockerfile
    assert "python scripts/verify_baseline.py" in dockerfile
    assert 'USER 1000:1000' in dockerfile
    assert 'ENTRYPOINT ["python", "castem_pipeline_gui_scientific.py"]' in dockerfile
    assert "container-output" in compose
    assert "privileged:" not in compose
    assert "/var/run/docker.sock" not in compose
    assert "docker compose run --rm mesher" in guide
    assert "does not add a display server" in guide
    assert "docs/docker.md" in readme
    assert "docker build" in workflow
    assert "--validate-only" in workflow
    assert "mode = python_only" in example
