# Minimal Docker example

`constant-planes.ini` creates a small, source-free Python-only HEXA8 mesh
between two parallel constant surfaces. It needs no CSV inputs, Cast3M, Gmsh,
or host Python installation.

From the repository root:

```console
docker compose build
docker compose run --rm mesher --headless examples/docker/constant-planes.ini --validate-only
docker compose run --rm mesher --headless examples/docker/constant-planes.ini
```

The Compose bind mount maps the configured `_runtime` path to the host's
`container-output` directory. See [the complete container guide](../../docs/docker.md)
for diagrams, terminology, custom cases, and troubleshooting.
