"""Tagged logging: [ORCHESTRATOR] [AGENT] [VALIDATION] [STATE UPDATE] [RETRY] [ERROR]."""
import logging
import sys
from pathlib import Path

_LOGGER = logging.getLogger("pm")


def setup_logging(log_file: Path | None = None, level: int = logging.INFO) -> None:
    _LOGGER.setLevel(level)
    _LOGGER.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    _LOGGER.addHandler(console)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        fh.setFormatter(fmt)
        _LOGGER.addHandler(fh)
    _LOGGER.propagate = False


def log(tag: str, message: str, level: int = logging.INFO) -> None:
    _LOGGER.log(level, "[%s] %s", tag, message)
