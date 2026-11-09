"""Compatibility entry: the /api/v1 handlers live in lutetia.web.api_v1; app.py and older imports keep using register_api from here."""
from .api_v1 import register_api

__all__ = ["register_api"]
