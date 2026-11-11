"""The unit tests run offline: tracing is switched off, the apps behave the same."""

import os

os.environ.setdefault("OPENGRADE_DISABLED", "1")
