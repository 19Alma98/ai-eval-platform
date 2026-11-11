"""Getting-started Bonus: inline dataset + evaluate → experiment URL."""

from __future__ import annotations

import os

from openai import OpenAI
from opengrade import Opengrade

og = Opengrade(project="demo", service_name="getting-started-bonus")

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


@og.trace
def ask(question: str) -> str:
    r = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": question}],
    )
    return r.choices[0].message.content or ""


def main() -> None:
    result = og.evaluate(
        dataset=ROWS,
        task=lambda item: ask(str(item.input)),  # each item becomes a trace
        metrics=["correctness", "latency"],
        name="getting-started-bonus",
        params={"model": MODEL},
    )
    print(result.summary())
    print(result.url)


if __name__ == "__main__":
    main()
