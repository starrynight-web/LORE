"""Owned freshness checks: claim verify, review stamp, product-pin heuristic."""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from lore.core.okf import Doc

_PATH_TOKEN = re.compile(
    r"`([^`\n]{1,200})`"
    r"|"
    r"(?<![A-Za-z0-9_/.-])((?:(?:\./|\.\./)?(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.(?:py|js|ts|tsx|jsx|md|json|ya?ml|toml|sh|go|rs|txt)))"
)
_SCRIPT_REF = re.compile(
    r"\b(?:npm|pnpm|yarn|npx)\s+(?:run\s+)?([A-Za-z0-9:_-]+)",
    re.IGNORECASE,
)
_PRODUCT_AGE_DAYS = 30


def _today() -> date:
    return datetime.now(UTC).date()


def _parse_verified(raw: Any) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _is_unverifiable(token: str) -> bool:
    lowered = token.lower()
    if lowered.startswith(("http://", "https://", "mailto:")):
        return True
    if token.startswith(("~", "/", "\\\\")) or "$" in token or "%" in token:
        return True
    if "*" in token or "{" in token:
        return True
    # MCP / namespaced ids that are not filesystem paths.
    if token.count("/") == 1 and not Path(token).suffix and not token.startswith((".", "/")):
        first = token.split("/", 1)[0]
        if first.lower() in {"microsoft", "azure", "google", "aws", "github"}:
            return True
    return False


def _extract_path_claims(body: str) -> list[str]:
    claims: list[str] = []
    seen: set[str] = set()
    for match in _PATH_TOKEN.finditer(body):
        token = (match.group(1) or match.group(2) or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        claims.append(token)
    return claims


def _package_scripts(project: Path) -> set[str]:
    package = project / "package.json"
    if not package.is_file():
        return set()
    try:
        import json

        data = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return set()
    return {str(name) for name in scripts}


def _git_touched_since(project: Path, verified: date, patterns: list[str]) -> bool:
    if not (project / ".git").exists() and not (project / ".git").is_file():
        return False
    since = verified.isoformat()
    for pattern in patterns:
        try:
            completed = subprocess.run(
                [
                    "git",
                    "-C",
                    str(project),
                    "log",
                    "--since",
                    since,
                    "--pretty=format:1",
                    "-n",
                    "1",
                    "--",
                    pattern,
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if completed.returncode == 0 and completed.stdout.strip():
            return True
    return False


def check_freshness(
    doc: Doc,
    *,
    project: Path | None = None,
    stamp: bool = False,
) -> dict[str, Any]:
    """Return a freshness report; never blocks approval."""
    body = doc.body or ""
    header = doc.header
    existing_raw = header.get("governance")
    existing = existing_raw if isinstance(existing_raw, dict) else {}
    prior_raw = existing.get("freshness")
    prior = prior_raw if isinstance(prior_raw, dict) else {}

    claims_ok = 0
    claims_stale: list[str] = []
    claims_unverifiable = 0

    root = project if project is not None else Path.cwd()
    scripts = _package_scripts(root)

    for token in _extract_path_claims(body):
        if _is_unverifiable(token):
            claims_unverifiable += 1
            continue
        # Script-like tokens without a path separator are handled below.
        if "/" not in token and "\\" not in token:
            claims_unverifiable += 1
            continue
        candidate = (root / token).resolve() if not Path(token).is_absolute() else Path(token)
        try:
            exists = candidate.exists()
        except OSError:
            exists = False
        if exists:
            claims_ok += 1
        else:
            # Also try relative to skill directory when the doc has a path.
            skill_hit = False
            if doc.path is not None:
                alt = (doc.path.parent / token).resolve()
                try:
                    skill_hit = alt.exists()
                except OSError:
                    skill_hit = False
            if skill_hit:
                claims_ok += 1
            else:
                claims_stale.append(token)

    for match in _SCRIPT_REF.finditer(body):
        name = match.group(1)
        if name.lower() in {"install", "ci", "exec", "dlx", "create", "init", "add", "remove"}:
            claims_unverifiable += 1
            continue
        if not scripts:
            claims_unverifiable += 1
            continue
        if name in scripts:
            claims_ok += 1
        else:
            claims_stale.append(f"script:{name}")

    verified_at = _today().isoformat() if stamp else (str(prior.get("verified_at") or "") or None)
    verified: date | None
    if stamp:
        verified = _today()
    else:
        verified = _parse_verified(prior.get("verified_at") or verified_at)

    status = "current"
    if claims_stale:
        status = "aging"

    covers = header.get("covers")
    cover_list = [str(item) for item in covers] if isinstance(covers, list) else []
    if verified is not None and cover_list and _git_touched_since(root, verified, cover_list):
        status = "aging"

    product = str(header.get("product") or "").strip()
    product_version = str(header.get("product_version") or "").strip()
    if (
        product
        and product_version
        and verified is not None
        and _today() - verified > timedelta(days=_PRODUCT_AGE_DAYS)
    ):
        status = "aging"

    return {
        "status": status,
        "verified_at": verified_at or (verified.isoformat() if verified else None),
        "claims_ok": claims_ok,
        "claims_stale": claims_stale,
        "claims_unverifiable": claims_unverifiable,
    }
