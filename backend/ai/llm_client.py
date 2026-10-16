"""Minimal OpenAI-compatible chat client (standard library only).

Works with OpenAI or any OpenAI-compatible endpoint (OPENAI_BASE_URL). The key
stays on the server; nothing here is ever sent to the browser.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import config


class LLMUnavailable(RuntimeError):
    pass


def llm_available() -> bool:
    config.refresh_llm_settings()
    return bool(config.OPENAI_API_KEY)


def model_name() -> str:
    config.refresh_llm_settings()
    return config.OPENAI_MODEL


def chat_message(messages: list[dict], *, tools: list[dict] | None = None, json_mode: bool = False,
                 temperature: float = 0.1, timeout: int = 90, response_format: dict | None = None) -> dict:
    """Return the assistant message dict ({'content': ..., 'tool_calls': [...]})."""
    if not llm_available():
        raise LLMUnavailable("No OPENAI_API_KEY configured on the server")
    base = (config.OPENAI_BASE_URL or "https://api.openai.com/v1").rstrip("/")
    body: dict = {"model": config.OPENAI_MODEL, "messages": messages, "temperature": temperature}
    if response_format:                       # e.g. {"type": "json_schema", ...} strict structured output
        body["response_format"] = response_format
    elif json_mode:
        body["response_format"] = {"type": "json_object"}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    req = urllib.request.Request(
        f"{base}/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode(errors="replace")
        raise LLMUnavailable(f"LLM API error {e.code}: {detail}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LLMUnavailable(f"LLM API unreachable: {e}") from e
    try:
        return data["choices"][0]["message"]
    except (KeyError, IndexError) as e:
        raise LLMUnavailable("LLM API returned an unexpected response shape") from e


def chat(messages: list[dict], json_mode: bool = False, temperature: float = 0.1, timeout: int = 90,
         response_format: dict | None = None) -> str:
    return chat_message(messages, json_mode=json_mode, temperature=temperature, timeout=timeout,
                        response_format=response_format).get("content") or ""
