import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from app.core.config import settings

# ── Initialization ───────────────────────────────────────────

def setup_logging():
    """
    Configure robust logging using properties from Settings.
    Mimics a properties-driven configuration (like SLF4J/Logback).
    """
    # 1. Determine Level (String to logging constant)
    level_str = settings.log_level.upper()
    if settings.debug:
        level_str = "DEBUG"
    
    level = getattr(logging, level_str, logging.INFO)
    
    # 2. Prepare Handlers
    handlers = []
    
    if settings.log_to_console:
        handlers.append(logging.StreamHandler(sys.stdout))
        
    if settings.log_to_file:
        log_path = Path(settings.log_file_path)
        log_path.parent.mkdir(exist_ok=True)
        
        handlers.append(
            RotatingFileHandler(
                log_path,
                maxBytes=10*1024*1024,
                backupCount=5,
                encoding="utf-8"
            )
        )

    # 3. Apply Configuration
    logging.basicConfig(
        level=level,
        format=settings.log_format,
        handlers=handlers,
        force=True  # Overwrite any existing root config
    )

    # 4. Library Tweaks
    if not settings.debug:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    
    # Sync uvicorn logs
    for name in ["uvicorn.access", "uvicorn.error"]:
        logger_lib = logging.getLogger(name)
        logger_lib.handlers = handlers
        logger_lib.propagate = False

    logger = logging.getLogger("trustgram")
    logger.info(f"Logging configured via properties. Level: {level_str}")
    if settings.log_to_file:
        logger.info(f"Log path: {settings.log_file_path}")

    return logger

# Default logger instance
logger = logging.getLogger("trustgram")
