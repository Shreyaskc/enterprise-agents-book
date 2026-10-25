# SPDX-License-Identifier: MIT
"""Optional schema-constrained Ollama action proposals; no native tools payload.

Live checks require explicit approval and fresh evidence separate from deterministic tests.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from typing import Callable
import urllib.request

from .contracts import Context, Rejected, TOOL_ARGUMENTS, ToolCall, canonical, identifier, text
from .storage import Store

PLAN_SCHEMA = {
    "oneOf": [
        {"type": "object", "additionalProperties": False, "required": ["name", "arguments"],
         "properties": {"name": {"const": name},
                        "arguments": {"type": "object", "additionalProperties": False,
                                      "required": [key], "properties": {key: ({"type": "string", "minLength": 1, "maxLength": 240, "pattern": "^[^\\u0000-\\u001f]+$"} if key == "query" else {"type": "string", "minLength": 1, "maxLength": 80, "pattern": "^[A-Za-z0-9_-]+$"})}}}}
        for name, key in TOOL_ARGUMENTS.items()
    ]
}


@dataclass(frozen=True)
class LocalModelApproval:
    approval_id: str
    tenant: str
    principal: str
    model: str
    model_sha256: str
    server_version: str
    expires_at: float
    maximum_requests: int = 1
    maximum_output_tokens: int = 128


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_: object, **__: object) -> None:
        raise Rejected("model_redirect_denied")


def _http(payload: dict) -> dict:
    # No arbitrary URLs, environment proxy, redirects, downloads, retry, or paid provider.
    request = urllib.request.Request("http://127.0.0.1:11434/api/chat",
                                     data=canonical(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=30) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise Rejected("model_response_too_large")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise Rejected("invalid_model_response") from exc


class OllamaAdapter:
    """Human approval object is supplied by trusted application code, not the model.

    The local demo does not authenticate humans or attest the Ollama installation.
    Deny server egress externally; a loopback endpoint alone cannot prove local inference.
    """

    def __init__(self, store: Store, transport: Callable[[dict], dict] = _http, *, on_reserved=None):
        self.store = store
        self.transport = transport
        self.on_reserved = on_reserved

    def plan(self, ctx: Context, question: str, approval: LocalModelApproval | None) -> dict:
        if approval is None or os.environ.get("NORTHSTAR_ENABLE_LOCAL_MODEL") != "1":
            raise Rejected("model_not_approved")
        identifier(approval.approval_id)
        if (approval.tenant, approval.principal) != (ctx.tenant, ctx.principal):
            raise Rejected("model_approval_scope")
        if approval.expires_at <= self.store.now():
            raise Rejected("model_approval_expired")
        text(approval.model, maximum=100)
        text(approval.server_version, maximum=50)
        if not re.fullmatch(r"[a-f0-9]{64}", approval.model_sha256) or "cloud" in approval.model.lower():
            raise Rejected("unreviewed_model")
        if type(approval.maximum_requests) is not int or not 1 <= approval.maximum_requests <= 3:
            raise Rejected("invalid_model_budget")
        if type(approval.maximum_output_tokens) is not int or not 1 <= approval.maximum_output_tokens <= 256:
            raise Rejected("invalid_model_budget")
        question = text(question, maximum=2000)
        self.store.reserve(ctx, "model-" + approval.approval_id, approval.maximum_requests)
        self.store.event(ctx, "model_reserved", {"mode": "optional_local_model", "status": "reserved"},
                         run_id="model-" + approval.approval_id)
        if self.on_reserved:
            self.on_reserved()
        payload = {"model": approval.model, "stream": False, "keep_alive": 0, "think": False,
                   "format": PLAN_SCHEMA, "options": {"temperature": 0, "num_predict": approval.maximum_output_tokens,
                                                       "num_ctx": 4096, "seed": 7},
                   "messages": [{"role": "system", "content": "Return one read-only tool call matching this JSON schema: " + canonical(PLAN_SCHEMA)},
                                {"role": "user", "content": question}]}
        response = self.transport(payload)  # No automatic retry after ambiguous outcome.
        if type(response) is not dict:
            raise Rejected("invalid_model_response")
        for field in ("prompt_eval_count", "eval_count"):
            value = response.get(field)
            if value is not None and (type(value) is not int or value < 0 or (field == "eval_count" and value > approval.maximum_output_tokens)):
                raise Rejected("invalid_model_usage")
        if response.get("done") is not True or response.get("model") != approval.model:
            raise Rejected("invalid_model_response")
        try:
            call = ToolCall.parse(json.loads(response["message"]["content"]))
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise Rejected("invalid_model_response") from exc
        # Only returns a proposal; tool permissions still apply at execution.
        return {"mode": "optional_local_model", "tool_call": {"name": call.name, "arguments": call.arguments},
                "server_version_declared": approval.server_version,
                "model_sha256_declared": approval.model_sha256,
                "usage_reported": {k: response.get(k) for k in ("prompt_eval_count", "eval_count")}}
