"""Decoy health helper. Do not edit for the API-shape quality task."""


def health_probe() -> dict[str, str]:
    return {"ok": "true"}
