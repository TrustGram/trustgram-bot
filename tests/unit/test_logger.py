import logging
from unittest.mock import patch, MagicMock
import pytest
from app.core.logger import setup_logging

def test_setup_logging_production_level():
    """Test setup_logging sets WARNING for sqlalchemy."""
    with patch("app.core.logger.settings") as mock_settings:
        mock_settings.log_level = "INFO"
        mock_settings.log_to_console = True
        mock_settings.log_to_file = False
        mock_settings.log_format = "%(message)s"
        
        # We need to mock logging.basicConfig and getLogger
        with patch("logging.basicConfig") as mock_basic:
            with patch("logging.getLogger") as mock_get_logger:
                mock_engine_logger = MagicMock()
                # Return mock_engine_logger when "sqlalchemy.engine" is requested
                mock_get_logger.side_effect = lambda name: mock_engine_logger if name == "sqlalchemy.engine" else MagicMock()
                
                setup_logging()
                
                # Check if sqlalchemy.engine level was set to WARNING
                mock_engine_logger.setLevel.assert_any_call(logging.WARNING)

def test_setup_logging_file_handler_creation():
    """Test that log directory is created when log_to_file is True."""
    with patch("app.core.logger.settings") as mock_settings:
        mock_settings.log_level = "INFO"
        mock_settings.log_to_file = True
        mock_settings.log_file_path = "test_logs/test.log"
        mock_settings.log_to_console = False
        mock_settings.log_format = "%(message)s"
        
        with patch("app.core.logger.Path") as mock_path:
            mock_file_path = MagicMock()
            mock_path.return_value = mock_file_path
            
            with patch("logging.basicConfig"):
                with patch("app.core.logger.RotatingFileHandler"):
                    setup_logging()
                    # Check if mkdir was called on parent
                    mock_file_path.parent.mkdir.assert_called_once_with(exist_ok=True)

def test_setup_logging_invalid_level_defaults_to_info():
    """If an invalid log level string is provided, it should default to INFO."""
    with patch("app.core.logger.settings") as mock_settings:
        mock_settings.log_level = "INVALID_LEVEL"
        mock_settings.log_to_console = True
        mock_settings.log_to_file = False
        
        with patch("logging.basicConfig") as mock_basic:
            setup_logging()
            # Check basicConfig was called with INFO (default)
            args, kwargs = mock_basic.call_args
            assert kwargs["level"] == logging.INFO
