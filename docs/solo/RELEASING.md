# Releasing Lore Solo

How a `lore-solo` release is produced, what artifacts exist, and who publishes
what. Git pushes, tags, workflow runs, and the GitHub release are
maintainer-owned actions; PyPI upload is user-owned.

## Two manifests, on purpose

- **Source `lore/site_bundles.json` is intentionally empty**
  (`{"schema_version":1,"lore_version":"<version>","bundles":{}}`). A checkout
  therefore never pretends to know release archives, and a release build with
  `LORE_RELEASE_BUILD=1` fails closed against that empty manifest by design —
  that rejection is the expected guard, not a bug.
- **The authoritative manifest is generated in the workflow.** The `wheel` job
  runs `scripts/assemble_site_manifest.py` over the site archives the `site`
  job built and smoke-tested, pins them into `lore/site_bundles.json`, and only
  then builds the release wheel/sdist with `LORE_RELEASE_BUILD=1`. The pinned
  manifest ships inside the release packages; it never lands back in source.

## Workflow

`.github/workflows/release.yml` runs on `workflow_dispatch` (explicit version)
and on `push` of `v*` tags. It does not publish anything itself.

1. `verify` — reads the version from `pyproject.toml`, confirms
   `lore.__version__` matches, and confirms the requested version (dispatch
   input or tag name, `v` prefix allowed) matches the source. Emits that
   version for downstream jobs, then runs ruff, mypy, and the full pytest
   suite.
2. `site` (matrix: ubuntu-22.04, windows-2022, macos-15) — builds the
   platform site bundle under Node 22, builds a wheel, and runs the full
   `smoke_install` against both. Uploads `site-<platform>` artifacts.
3. `wheel` — downloads every verified `site-*` artifact, assembles the pinned
   manifest, exports `release_constraints.txt`, builds the release wheel+sdist,
   runs `twine check --strict`, proves the sdist rebuilds a wheel, then runs
   core and full smokes. Uploads `release-packages` (wheel, sdist, manifest,
   constraints).
4. `images` — rebuilds the `mcp`/`full` container images in release mode from
   those staged artifacts (`LORE_RELEASE_ARTIFACTS=1`, real Docker on the
   runner) and smokes them. Uploads `release-images` (docker save tarball)
   for inspection only.

All artifacts must pass the full platform smokes and the Linux real-Docker
image gate before the release is published. **Do not tag until CI on the
candidate commit is fully green.**

## Publishing sequence

1. Land everything on the release branch; bump `pyproject.toml`,
   `lore/__init__.py`, and the `lore_version` placeholder in
   `lore/site_bundles.json` together; `uv lock` refreshes the root version.
2. Push the source, wait for the full CI suite on that commit, then tag `v0.2.2`
   and push the tag. The release workflow runs on the tag.
3. Download the `release-packages` artifact, verify it contains the wheel,
   sdist, pinned `site_bundles.json`, and `release_constraints.txt`, then
   attach those files plus the `site-*` archives to the GitHub release and
   publish it. The GitHub source archive (the auto-generated tag zip) is **not**
   the PyPI package — never upload it.
4. Only after the GitHub release assets are live does the user publish to PyPI,
   and only from the verified release artifacts — never from a stale `dist/`
   or a locally built placeholder wheel. Stage them in a clean, dedicated
   directory:

   ```bash
   mkdir -p dist/pypi-0.2.2
   # copy the verified release wheel + sdist into dist/pypi-0.2.2/
   cd dist/pypi-0.2.2
   uvx twine check --strict lore_solo-0.2.2-py3-none-any.whl lore_solo-0.2.2.tar.gz
   uvx twine upload lore_solo-0.2.2-py3-none-any.whl lore_solo-0.2.2.tar.gz
   ```

## What Docker is (and is not)

Container images are an optional distribution/demo path, not the primary one.
The workflow builds and smokes them in release mode so a broken release layout
fails before publication, but no image is pushed to a registry automatically
and `docker save` tarballs remain a manual, no-network convenience.
