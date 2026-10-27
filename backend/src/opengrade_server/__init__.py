"""OpenGrade backend."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    __version__ = _version("opengrade-ai-server")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0"
