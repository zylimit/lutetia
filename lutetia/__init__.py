"""Lutetia: collector for the Paris project's IoT data sources (GPS51 + Dingtek)."""
from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version("lutetia")
except PackageNotFoundError:  # running from a bare source tree that was never pip-installed
    __version__ = "0+unknown"
