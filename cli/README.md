# aiobs-cli (deprecated)

The `aiobs` console script now ships with **`aiobs-server`**:

```bash
pip install 'aiobs[ui]'   # or: pip install aiobs-server
aiobs ui                  # local API + UI (SQLite by default)
aiobs check --policy ...  # release gate
```

This package remains temporarily for older docs/workflows; prefer `aiobs-server`.
See `docs/08-cli-ci.md`.
