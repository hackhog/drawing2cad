# 25. Poetry for the Python projects

Date: 2026-10-18

## Status

Accepted. Replaces uv and the uv_build and setuptools build backends for `app/backend` and `drawing2cad-mcp`.

## Context

The web backend used uv with the uv_build backend. The MCP package used setuptools.
The two projects had two build backends and one installer that the team does not use for other Python work.
The backend lock became out of date once after a version change of the MCP package.

## Decision

- Both projects use Poetry 2.4.1 and the poetry-core build backend.
  CI and both Dockerfiles install this exact version.
- Each project has a `poetry.lock`. The `[project]` table of each `pyproject.toml` stays the package metadata.
- Each project has a `poetry.toml` that keeps the environment in `.venv` in the project directory, as with uv.
- `[tool.poetry.dependencies] python` limits only the lock range to Python versions earlier than 3.15,
  because build123d 0.13.0 requires Python earlier than 3.15.
  `requires-python` stays `>=3.12` for the backend and `>=3.11` for the MCP package.
- The backend has the MCP package as a path dependency with `develop = false` and the `cad` extra.
  Poetry builds it as a wheel and installs that wheel.
- The backend dev group (`[dependency-groups] dev`) contains pytest and Playwright.
  Production installations use `poetry install --only main`.
- The MCP package keeps its `cad` and `test` extras. Development installations add `--extras "cad test"`.
- Poetry includes all files of the package directory that Git does not ignore.
  This includes `origins.json`, `glyph_templates.json`, and `py.typed`.
- The images install the dependencies with Poetry and install each root package from a wheel.
  Poetry has its own environment in the images, separate from the application environment.
- The backend CI job runs `poetry lock` and stops if the backend lock changes.
- The MCP CI job tests the package only in its Linux test image, which Poetry installs from the lock.
  The job also builds the wheel and sdist with the Poetry of that image and checks their content.
  A Linux container is the supported test environment, also on Windows through WSL.

## Consequences

- After a change to the version or dependencies of the MCP package, run `poetry lock` in `app/backend/` and commit the lock.
- `poetry install` does not install a changed MCP source again while its version stays the same.
  Remove the installed copy with `poetry run python -m pip uninstall -y drawing2cad-mcp` first.
  Poetry has no command to install one package again. uv had `--reinstall-package`.
- Without `poetry lock`, `poetry install` keeps the locked MCP version and reports no error. The CI lock check finds this condition.
- `drawing2cad-mcp/requirements-tested.txt` records a previous pip environment. It is not an installation path.
- Earlier ADRs and run records that show uv commands stay unchanged as history.

## Alternatives considered

| Alternative | Reason for rejection |
|---|---|
| Keep uv | The team selected Poetry for the Python projects |
| Poetry-only `[tool.poetry]` metadata | The PEP 621 `[project]` table keeps the metadata readable by other tools |
| Test dependencies as a Poetry group in the MCP package | The `test` extra must stay available; a second list would duplicate it |
