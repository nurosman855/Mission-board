"""Optional one-call OpenAI Responses adapter. Never called by importing.

Only use with explicit provider/model approval and provider-side hard spend
controls. An API response is NOT market evidence or a verified citation.
"""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mission_control_bridge import HandoffError


PROPOSAL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "hypothesis": {"type": "string"},
        "gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hypothesis", "gaps"],
}


class OpenAIResearchProposalAdapter:
    """No web tools; response constrained to an unverified hypothesis."""

    def __init__(self, *, api_key: str, model: str,
                 send: Callable[[dict[str, Any], str], dict[str, Any]] | None = None):
        if not isinstance(api_key, str) or not api_key.strip() or not isinstance(model, str) or not model.strip():
            raise HandoffError("Explicit OpenAI key and model required")
        self._key, self._model = api_key, model
        self._send = send or self._http

    @staticmethod
    def _http(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                data = json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError):
            # Avoid leaking response bodies, secrets, or prompt text in errors.
            raise HandoffError("OpenAI response transport failed") from None
        if not isinstance(data, dict):
            raise HandoffError("Malformed provider response")
        return data

    def __call__(self, *, prompt: str, max_output_tokens: int) -> dict[str, Any]:
        payload = {
            "model": self._model, "input": prompt, "store": False,
            "max_output_tokens": max_output_tokens,
            "text": {"format": {"type": "json_schema", "name": "research_hypothesis",
                                "strict": True, "schema": PROPOSAL_SCHEMA}},
        }
        response = self._send(payload, self._key)
        if not isinstance(response, dict) or response.get("status") != "completed":
            raise HandoffError("Provider response incomplete or unavailable")
        texts = []
        for item in response.get("output", []):
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if content.get("type") == "refusal":
                    raise HandoffError("Provider refused proposal")
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    texts.append(content["text"])
        if len(texts) != 1:
            raise HandoffError("Provider did not supply one structured answer")
        try:
            proposal = json.loads(texts[0])
        except ValueError:
            raise HandoffError("Provider output is not JSON") from None
        if not isinstance(proposal, dict) or set(proposal) != {"hypothesis", "gaps"}:
            raise HandoffError("Provider output violates expected fields")
        return proposal
