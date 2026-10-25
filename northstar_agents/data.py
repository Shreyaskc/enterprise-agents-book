# SPDX-License-Identifier: MIT
"""Versioned fixture loading; synthetic records never masquerade as UCI rows."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contracts import Rejected

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "data/fixtures/northstar_synthetic.json"


def load_fixture() -> dict:
    raw = FIXTURE.read_bytes()
    manifest = json.loads((ROOT / "data/manifests/synthetic.json").read_text())
    if hashlib.sha256(raw).hexdigest() != manifest["sha256"]:
        raise Rejected("fixture_checksum_mismatch")
    return json.loads(raw)


def scoped(records: list[dict], tenant: str, key: str, value: str) -> dict:
    for record in records:
        if record["tenant"] == tenant and record[key] == value:
            return dict(record)
    raise Rejected("record_unavailable")
