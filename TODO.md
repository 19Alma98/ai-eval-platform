# TODO

Open items from the RAG evaluation review (2026-10-08). Fixed items are in git history.

## Tooling

- [ ] **No frontend `test` script.** Unit tests use `node:test` and only run with
  `node --import tsx --test <files>`. Add `"test"` to `frontend/package.json` and run it in CI.


## Performance

- [ ] **Live list N+1.** `ListLiveInteractions` loads scores and review per row. Batch-load scores
  and reviews for a page.
- [ ] **`failed_only` can scan the whole project** when few interactions failed (pages through all
  rows). Persist the verdict per interaction (e.g. `has_failed_score`) at scoring time and filter in
  SQL.
