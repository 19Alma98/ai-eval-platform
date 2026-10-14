"""Console entry point ``aiobs``: delegates to the server CLI when installed."""

from __future__ import annotations

import sys
from importlib import import_module
from importlib.util import find_spec

INSTALL_HINT = (
    "aiobs: server components are not installed.\n"
    "Install them with:\n"
    '  pip install "aiobs-eval[ui]"\n'
)


def main() -> None:
    if find_spec("aiobs_server") is None:
        sys.stderr.write(INSTALL_HINT)
        sys.exit(1)
    import_module("aiobs_server.cli").app()


if __name__ == "__main__":
    main()
