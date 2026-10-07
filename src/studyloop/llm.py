"""Optional LLM access. Nothing in StudyLoop requires it; ``get_client()`` returns ``None`` unless
the person configured one through the environment:

    STUDYLOOP_LLM=ollama     STUDYLOOP_LLM_MODEL=qwen2.5:3b   (CPU Ollama at localhost:11434)
    STUDYLOOP_LLM=anthropic  ANTHROPIC_API_KEY=...            STUDYLOOP_LLM_MODEL=claude-haiku-4-5
    STUDYLOOP_LLM=openai     OPENAI_API_KEY=...               STUDYLOOP_OPENAI_BASE_URL=...

Standard library only (``urllib``). Every caller must treat the model's output as untrusted text:
answers are accepted only when their quotes are found in the book.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Protocol


class LLMError(RuntimeError):
    pass


class Client(Protocol):
    name: str
    model: str

    def complete(self, prompt: str, system: str = "", max_tokens: int = 700) -> str: ...


def _post(url: str, body: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise LLMError(f"HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise LLMError(f"could not reach the model: {exc}") from exc


class Ollama:
    name = "ollama"

    def __init__(self, model: str, host: str, timeout: float = 180.0):
        self.model, self.host, self.timeout = model, host.rstrip("/"), timeout

    def complete(self, prompt: str, system: str = "", max_tokens: int = 700) -> str:
        body = {
            "model": self.model, "prompt": prompt, "system": system, "stream": False,
            "options": {"temperature": 0.1, "num_predict": max_tokens},
        }
        return _post(self.host + "/api/generate", body, {}, self.timeout).get("response", "")


class Anthropic:
    name = "anthropic"

    def __init__(self, model: str, key: str, timeout: float = 90.0):
        self.model, self.key, self.timeout = model, key, timeout

    def complete(self, prompt: str, system: str = "", max_tokens: int = 700) -> str:
        body = {
            "model": self.model, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": prompt}], "temperature": 0.1,
        }
        h = {"x-api-key": self.key, "anthropic-version": "2023-06-01"}
        data = _post("https://api.anthropic.com/v1/messages", body, h, self.timeout)
        return "".join(b.get("text", "") for b in data.get("content", []))


class OpenAICompatible:
    name = "openai"

    def __init__(self, model: str, key: str, base: str, timeout: float = 90.0):
        self.model, self.key, self.base, self.timeout = model, key, base.rstrip("/"), timeout

    def complete(self, prompt: str, system: str = "", max_tokens: int = 700) -> str:
        msgs = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        body = {"model": self.model, "messages": msgs, "max_tokens": max_tokens, "temperature": 0.1}
        data = _post(self.base + "/chat/completions", body,
                     {"Authorization": f"Bearer {self.key}"}, self.timeout)
        return data["choices"][0]["message"]["content"]


def get_client() -> Client | None:
    kind = os.environ.get("STUDYLOOP_LLM", "").strip().lower()
    model = os.environ.get("STUDYLOOP_LLM_MODEL", "")
    if kind == "ollama":
        host = os.environ.get("STUDYLOOP_OLLAMA_HOST", "http://localhost:11434")
        return Ollama(model or "qwen2.5:3b", host)
    if kind == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        return Anthropic(model or "claude-haiku-4-5", os.environ["ANTHROPIC_API_KEY"])
    if kind == "openai" and os.environ.get("OPENAI_API_KEY"):
        base = os.environ.get("STUDYLOOP_OPENAI_BASE_URL", "https://api.openai.com/v1")
        return OpenAICompatible(model or "gpt-4o-mini", os.environ["OPENAI_API_KEY"], base)
    return None


def status() -> dict:
    c = get_client()
    kind = os.environ.get("STUDYLOOP_LLM", "").strip().lower()
    return {
        "configured": c is not None,
        "provider": c.name if c else None,
        "model": c.model if c else None,
        "note": (
            None if c or not kind
            else f"STUDYLOOP_LLM={kind} is set but its key is missing; running without a model"
        ),
    }


def parse_json(text: str) -> dict | list | None:
    """First JSON object or array in a model reply, or None."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M)
    for opener, closer in (("{", "}"), ("[", "]")):
        a, b = text.find(opener), text.rfind(closer)
        if a != -1 and b > a:
            try:
                return json.loads(text[a : b + 1])
            except json.JSONDecodeError:
                continue
    return None
