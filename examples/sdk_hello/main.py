"""Minimal SDK hello: CHAIN parent + OpenAI-instrumentor LLM child via Ollama."""

from __future__ import annotations

import os

from openai import OpenAI

import opengrade

opengrade.set_tracking_uri(os.getenv("OPENGRADE_TRACKING_URI", "http://localhost:8000"))
opengrade.set_project(os.getenv("OPENGRADE_PROJECT_SLUG", "demo"))
opengrade.init(service_name="sdk-hello", instrument="auto")

client = OpenAI(
    base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434") + "/v1",
    api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
)
MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e2b")


@opengrade.trace
def ask(q: str) -> str:
    r = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": q}],
    )
    return r.choices[0].message.content or ""


def main() -> None:
    print(ask("ping"))
    opengrade.flush()


if __name__ == "__main__":
    main()
