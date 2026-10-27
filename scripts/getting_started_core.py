"""Getting-started Core: one CHAIN + LLM child span → project demo."""

from __future__ import annotations

import os

from openai import OpenAI

import opengrade

opengrade.set_tracking_uri(os.getenv("OPENGRADE_TRACKING_URI", "http://127.0.0.1:8000"))
opengrade.set_project(os.getenv("OPENGRADE_PROJECT_SLUG", "demo"))
opengrade.init(service_name="getting-started-core", instrument="auto")

base = os.getenv("OPENAI_BASE_URL") or (
    os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434") + "/v1"
)
client = OpenAI(base_url=base, api_key=os.getenv("OPENAI_API_KEY") or os.getenv("OLLAMA_API_KEY", "ollama"))
MODEL = os.getenv("OPENAI_MODEL") or os.getenv("OLLAMA_MODEL", "gemma4:e2b")


@opengrade.trace
def ask(q: str) -> str:
    r = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": q}],
    )
    return r.choices[0].message.content or ""


def main() -> None:
    print(ask("What is OpenGrade in one sentence?"))
    opengrade.flush()
    print("Open Traces in the UI for project demo.")


if __name__ == "__main__":
    main()
