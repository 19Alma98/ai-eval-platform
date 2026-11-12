# Evaluate a chat assistant

A recipe for multi-turn RAG assistants: the user asks "Do you have a Pro plan?", then
"How much does it cost?". The second question only makes sense with the first one, so the unit
under test is the **conversation so far plus the last question**.

Offline, OpenGrade scores the last answer of each scripted conversation. In production, it
groups real turns by session and scores the whole conversation once the user goes idle.

## 1. Write chat-shaped test cases

Each row holds the earlier turns in `input.history` and the question to answer in
`input.question`. `expected_output`, `expected_doc_ids` and `must_contain` describe the
**last** turn:

```jsonl
{"input": {"history": [{"role": "user", "content": "Do you have a Pro plan?"}, {"role": "assistant", "content": "Yes, we offer a Pro plan."}], "question": "How much does it cost?"}, "expected_output": "The Pro plan costs 8 dollars per user per month.", "expected_doc_ids": ["plans"], "must_contain": ["8 dollars"]}
{"input": {"history": [{"role": "user", "content": "Can I get a refund for last month?"}], "question": "What if I already used the seats?"}, "expected_output": "Unused seats are refunded; seats already used in the billing period are not.", "expected_doc_ids": ["billing"]}
{"input": {"history": [{"role": "user", "content": "I'm on the Business plan."}], "question": "Who is the CEO of Nimbus?"}, "answerable": false}
```

Chat-shaped inputs make the dataset `task_type: rag_chat` automatically. Include follow-ups
that cannot be answered (`answerable: false`): they are where chat assistants invent the most.

## 2. Make your app expose what the judges need

```python
from opengrade import Opengrade

og = Opengrade(project="support-chat")


@og.trace
def chat(history: list[dict], question: str) -> str:
    query = rewrite(history, question)       # "How much does the Pro plan cost?"
    og.set_search_query(query)               # → query_rewrite_faithfulness
    docs = retriever.search(query)
    og.set_retrieval_documents(docs)         # → retrieval metrics, groundedness, resolution
    return llm.generate(history, question, docs)
```

`set_search_query` records the standalone query your app actually sent to the retriever.
Without it `query_rewrite_faithfulness` is skipped; with it you can tell a retrieval problem
("found the wrong documents") from a rewriting problem ("searched for the wrong thing").

## 3. Run the experiment

```python
import opengrade


def task(item):
    turn = opengrade.chat_input(item)        # .history (list of ChatTurn), .question
    return chat([t.model_dump() for t in turn.history], turn.question)


result = og.evaluate(
    dataset="gold_chat.jsonl",
    task=task,
    metrics=[
        "hit_at_k", "must_contain",          # deterministic, last turn
        "groundedness", "correctness",       # last turn, judged with the history as context
        "query_rewrite_faithfulness",
        "conversation_consistency",
        "resolution",
    ],
    baseline="alias:main",
)
print(result.summary())
```

| Metric | Question it answers | Needs |
|---|---|---|
| `query_rewrite_faithfulness` | Does the search query mean what the user meant, given the history? | `set_search_query` |
| `conversation_consistency` | Do the assistant turns contradict each other or forget a user constraint? | at least two assistant turns |
| `resolution` | Did the last answer resolve the user's need, or correctly decline when the documents can't? | retrieved documents |
| `groundedness`, `correctness`, `answer_relevance` | The usual single-turn checks on the last answer, with the history used to interpret the question | as for single-turn RAG |
| `refusal` | Did it decline exactly the unanswerable follow-ups? | `answerable` labels |

All of them except the deterministic ones need a judge model on the server
([configuration](deploy.md#judge-credentials)). Without one they are skipped with
`judge not configured`, never scored as 0.

!!! note "What offline evaluation can and cannot see"
    In a test case only the **last** answer comes from your app; the earlier assistant turns are
    the ones you scripted. `conversation_consistency` therefore checks the new answer against that
    script. Drift that builds up over a long real conversation shows up in production, below.

The runnable version of this recipe, offline with fake models, is script 06 of the
[SDK tour](../examples/sdk_tour/README.md).

## 4. Watch real conversations

Give every turn of a conversation the same session id:

```python
@og.trace
def handle(conversation_id: str, history: list[dict], question: str) -> str:
    og.set_session(conversation_id)
    return chat(history, question)
```

**Production → Conversations** then lists sessions with their turns as a chat timeline. The
session judges (`query_rewrite_faithfulness`, `conversation_consistency`, `resolution`) score
the whole conversation:

- automatically, once a session has been idle for 15 minutes (checked every minute);
- on demand, with **Run session judges** on the conversation page.

They are off in the default metrics set: enable them in **Metrics** for the project.
**Conversations** shows a link to Metrics when they are off, instead of leaving only an `open`
status with no scores. A new turn after scoring re-opens the conversation, so it is scored
again when it goes idle.
`resolution` uses the documents of the last turn, so enable live scoring
(`og.init_tracing(live=True)`) for the documents to be stored with the turn.

## 5. Turn a bad conversation into a test case

A conversation that went wrong in production becomes a `rag_chat` test case with a
reviewed reference answer for the last turn. On the conversation page, **Add to test set**
asks for the test set, the correct answer and, for RAG test sets, the expected document ids.
The production answer is never copied as the reference: it is what is being tested.

The same from a script, with the REST API:

```bash
curl -X POST "$OPENGRADE/api/v1/projects/$PROJECT_ID/conversations/$SESSION_ID/promote" \
  -H "Authorization: Bearer $OPENGRADE_API_KEY" -H "Content-Type: application/json" \
  -d '{"dataset_id": "<dataset id>", "expected_output": "The Pro plan costs 8 dollars per user per month.", "expected_doc_ids": ["plans"]}'
```

Into a `rag_chat` dataset the item keeps the earlier turns as `history` (`"mode": "last_turn"`
drops them); into a `rag_qa` dataset it keeps only the last question. From the next run on, the gate catches that
regression before it ships again.
