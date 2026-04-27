"""파일 로깅 설정."""
from __future__ import annotations
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


def setup_logging(log_dir: Path | None = None) -> Path:
    log_dir = log_dir or (Path.home() / "AppData" / "Local" / "KStudio" / "logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    handler = TimedRotatingFileHandler(log_file, when="midnight", backupCount=14, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
    return log_file
