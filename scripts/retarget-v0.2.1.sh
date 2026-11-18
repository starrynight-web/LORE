#!/usr/bin/env bash
# Retarget v0.2.1 onto origin/solo (build_id fix) and trigger release-artifacts.
set -euo pipefail
cd "$(dirname "$0")/.."
git fetch origin solo
git checkout solo
git reset --hard origin/solo
git tag -d v0.2.1 2>/dev/null || true
git tag -a v0.2.1 -m "Lore Solo 0.2.1"
git push origin refs/tags/v0.2.1 --force
echo "Pushed v0.2.1 -> $(git rev-parse v0.2.1^{commit})"
echo "Watch: https://github.com/starrynight-web/LORE/actions/workflows/release.yml"
