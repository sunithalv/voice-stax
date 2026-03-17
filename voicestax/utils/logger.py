# VoiceStax/voicestax/utils/logger.py

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

# ── Library logger ───────────────────────────────────────────────────────────
logger = logging.getLogger("voicestax")
logger.addHandler(logging.NullHandler())

# Default log file at project root
_DEFAULT_LOG_FILE = Path(__file__).parent.parent.parent / "voicestax.log"


def setup_logging(
    level: str = "INFO",
    mode: str = "both",                  # "console" | "file" | "both"
    log_file: str | Path = _DEFAULT_LOG_FILE,
    max_bytes: int = 5 * 1024 * 1024,   # 5 MB
    backup_count: int = 3,
) -> logging.Logger:
    """
    Call this once from your application entry point (e.g. main.py).

    Examples
    --------
    Default (console + file, INFO level):
        setup_logging()

    Console only:
        setup_logging(mode="console")

    File only, verbose:
        setup_logging(mode="file", level="DEBUG")

    Custom log file:
        setup_logging(log_file="logs/myapp.log")
    """
    _logger = logging.getLogger("voicestax")
    _logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    _logger.handlers.clear()           # avoid duplicate handlers on re-calls
    _logger.propagate = False          # ← don't bubble up to app's root logger

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if mode in ("console", "both"):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        _logger.addHandler(console_handler)

    if mode in ("file", "both"):
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        _logger.addHandler(file_handler)

    # ── Session start banner ─────────────────────────────────────────────────
    _logger.info("=" * 60)
    _logger.info("  VoiceStax session started")
    _logger.info("=" * 60)

    return _logger