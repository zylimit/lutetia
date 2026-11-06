import logging
import sys


def setup(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
