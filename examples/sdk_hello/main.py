"""Minimal SDK hello: CHAIN parent + OpenAI-instrumentor LLM child via Ollama."""

from __future__ import annotations

import os

from openai import OpenAI
from opengrade import Opengrade

# Platform URL from OPENGRADE_TRACKING_URI (default http://localhost:8000). The project
# is created if it does not exist; tracing starts on the first traced call.
og = Opengrade(project=os.getenv("OPENGRADE_PROJECT", "demo"), service_name="sdk-hello")

client = OpenAI(
    base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434") + "/v1",
    api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
)
MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e2b")


@og.trace
def ask(q: str) -> str:
    r = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": q}],
    )
    return r.choices[0].message.content or ""


def main() -> None:
    print(ask("ping"))
    og.flush()


if __name__ == "__main__":
    main()
