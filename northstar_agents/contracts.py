# SPDX-License-Identifier: MIT
"""Strict boundary contracts. An annotation is not a JSON validator."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any


class Rejected(ValueError):
    """A safe, stable error code; do not put raw input into the message."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def text(value: Any, *, maximum: int = 240) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise Rejected("invalid_text")
    if any(ord(c) < 32 for c in value):
        raise Rejected("control_character")
    return value


def identifier(value: Any) -> str:
    value = text(value, maximum=80)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise Rejected("invalid_identifier")
    return value


def exact_keys(value: Any, keys: set[str]) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise Rejected("invalid_fields")
    return value


@dataclass(frozen=True)
class Context:
    """Injected by a trusted demo identity boundary, never read from a prompt."""

    tenant: str
    principal: str

    def __post_init__(self) -> None:
        identifier(self.tenant)
        identifier(self.principal)


TOOL_ARGUMENTS = {
    "lookup_case": "case_id",
    "lookup_invoice": "invoice_id",
    "search_policy": "query",
    "sales_signal": "stock_code",
}


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, str]

    @classmethod
    def parse(cls, value: Any) -> ToolCall:
        obj = exact_keys(value, {"name", "arguments"})
        name = text(obj["name"], maximum=40)
        if name not in TOOL_ARGUMENTS:
            raise Rejected("unknown_tool")
        key = TOOL_ARGUMENTS[name]
        args = exact_keys(obj["arguments"], {key})
        item = text(args[key]) if key == "query" else identifier(args[key])
        return cls(name, {key: item})

    def validated(self) -> ToolCall:
        return self.parse(asdict(self))


@dataclass(frozen=True)
class CaseAction:
    case_id: str
    invoice_id: str
    summary: str
    policy_version: str = "v3"
    kind: str = "create_local_case"
    schema_version: int = 1

    @classmethod
    def parse(cls, value: Any) -> CaseAction:
        obj = exact_keys(value, {
            "case_id", "invoice_id", "summary", "policy_version", "kind", "schema_version"
        })
        if type(obj["schema_version"]) is not int or obj["schema_version"] != 1:
            raise Rejected("unsupported_schema")
        if obj["kind"] != "create_local_case":
            raise Rejected("unsupported_action")
        return cls(identifier(obj["case_id"]), identifier(obj["invoice_id"]),
                   text(obj["summary"]), identifier(obj["policy_version"]))

    def validated(self) -> CaseAction:
        return self.parse(asdict(self))

    def request_hash(self, ctx: Context) -> str:
        return digest({"tenant": ctx.tenant, "principal": ctx.principal,
                       "action": asdict(self.validated())})
