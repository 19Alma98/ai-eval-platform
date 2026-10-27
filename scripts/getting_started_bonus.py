"""Getting-started Bonus: inline dataset + evaluate → experiment URL."""

from __future__ import annotations

import os

from openai import OpenAI

import opengrade

opengrade.set_tracking_uri(os.getenv("OPENGRADE_TRACKING_URI", "http://127.0.0.1:8000"))
opengrade.set_project(os.getenv("OPENGRADE_PROJECT_SLUG", "demo"))
opengrade.init(service_name="getting-started-bonus", instrument="auto")

base = os.getenv("OPENAI_BASE_URL") or (
    os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434") + "/v1"
)
client = OpenAI(base_url=base, api_key=os.getenv("OPENAI_API_KEY") or os.getenv("OLLAMA_API_KEY", "ollama"))
MODEL = os.getenv("OPENAI_MODEL") or os.getenv("OLLAMA_MODEL", "gemma4:e2b")

ROWS = [
    {
        "input": "What is the capital of France?",
        "expected_output": "Paris",
        "expected_doc_ids": ["faq-capital"],
    },
    {
        "input": "What is 2 + 2?",
        "expected_output": "4",
        "expected_doc_ids": ["faq-math"],
    },
]


def task(item) -> str:
    r = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": str(item.input)}],
    )
    return r.choices[0].message.content or ""


def main() -> None:
    result = opengrade.evaluate(
        dataset=ROWS,
        task=task,
        task_type="rag_qa",
        metrics=["correctness", "latency"],
        name="getting-started-bonus",
        params={"model": MODEL},
    )
    print(result.summary())
    print(result.url)


if __name__ == "__main__":
    main()
