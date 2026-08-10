# Releasing

The project is currently pre-release. Before publishing a package, choose and
record a license.

## Checklist

1. Update the version in `pyproject.toml`.
2. Update `src/simple_db_mcp/__init__.py`.
3. Update `CHANGELOG.md`.
4. Sync dependencies:

```bash
uv sync
```

5. Run checks:

```bash
uv run ruff check .
uv run mypy src
uv run pytest
```

6. Build distributions:

```bash
uv build
```

7. Inspect `dist/`.
8. Commit the release changes.
9. Tag the release:

```bash
git tag v0.1.0
```

10. Publish when package metadata, license, and repository settings are ready:

```bash
uv publish
```
