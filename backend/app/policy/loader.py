from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .rules import PolicySpec

DEFAULT_POLICY_PATH = Path(__file__).with_name("default_policy.yaml")


def load_default_policy() -> PolicySpec:
    data = yaml.safe_load(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    return PolicySpec.model_validate(data)


def domain_of(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return (parsed.hostname or "").lower()


def build_context(
    *,
    action_type: str,
    action_params: dict[str, Any],
    page_url: str = "",
    page_title: str = "",
    agent: dict[str, Any] | None = None,
    run: dict[str, Any] | None = None,
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Flatten an action plus its surroundings into the shape policy rules address."""
    params = dict(action_params or {})
    target_url = str(params.get("url") or "")

    action: dict[str, Any] = {
        "type": action_type,
        "label": str(params.get("label") or ""),
        "text": str(params.get("text") or ""),
        "url": target_url,
        "domain": domain_of(target_url),
        "is_sensitive": bool(params.get("is_sensitive", False)),
        "params": params,
    }
    if "amount_usd" in params and params["amount_usd"] is not None:
        action["amount_usd"] = params["amount_usd"]

    return {
        "action": action,
        "page": {"url": page_url, "domain": domain_of(page_url), "title": page_title},
        "agent": agent or {},
        "run": run or {},
        "session": session or {},
    }
