"""Groq chat completions, waiting out the free tier's limits (8,000 tokens a minute per model)."""
import json
import os
import time

import requests


def _salvage(error_body):
    """gpt-oss sometimes answers as an invented tool call, which Groq rejects; the words are still inside."""
    try:
        call = json.loads(json.loads(error_body)["error"]["failed_generation"])
        args = call.get("arguments") or {}
        for key in ("text", "response", "content", "message"):
            if isinstance(args.get(key), str):
                return args[key]
        return next((v for v in args.values() if isinstance(v, str)), None)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def groq(model, messages, max_tokens=300, **extra):
    for attempt in range(12):
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                          headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
                          json={"model": model, "messages": messages, "max_tokens": max_tokens,
                                "reasoning_effort": "low", **extra}, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(min(float(r.headers.get("retry-after") or 2 ** attempt), 300))
            continue
        if r.status_code == 400 and "tool_use_failed" in r.text:
            text = _salvage(r.text)
            if text:
                return " ".join(text.split())
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"Groq {r.status_code}: {r.text[:300]}")
        return " ".join((r.json()["choices"][0]["message"]["content"] or "").split())
    raise RuntimeError(f"Groq kept refusing: {r.status_code} {r.text[:200]}")
