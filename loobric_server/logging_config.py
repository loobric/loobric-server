# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Logging configuration for Loobric using structlog.

This module configures structured logging with JSON output for production
and pretty-printed output for development.

Assumptions:
- structlog outputs JSON by default
- Context can be bound per-request (user_id, request_id)
- Log level is configurable via environment variable
- Development mode uses console renderer, production uses JSON
"""
import logging
import sys
from typing import Any, Dict, Optional

import structlog
from structlog.types import EventDict, Processor

from loobric_server.config import settings


def add_log_level(
    logger: logging.Logger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Add log level to event dict.
    
    Args:
        logger: Logger instance
        method_name: Name of the logging method
        event_dict: Event dictionary
        
    Returns:
        EventDict: Updated event dictionary with level
        
    Assumptions:
    - method_name corresponds to logging level
    """
    event_dict["level"] = method_name.upper()
    return event_dict


def configure_logging(
    log_level: Optional[str] = None,
    json_output: Optional[bool] = None
) -> None:
    """Configure structlog for the application.
    
    Args:
        log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_output: If True, output JSON; if False, pretty print
        
    Assumptions:
    - Defaults to INFO level
    - Defaults to JSON output in production
    - Uses console renderer in development
    """
    level = log_level or settings.log_level
    use_json = json_output if json_output is not None else True
    
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper()),
    )
    
    # Build processor chain
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    
    # Add JSON or console renderer
    if use_json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    
    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a logger instance.
    
    Args:
        name: Logger name (typically module name)
        
    Returns:
        BoundLogger: Configured structlog logger
        
    Assumptions:
    - configure_logging has been called
    - Logger can be bound with context
    """
    return structlog.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """Bind context variables to all subsequent log entries.
    
    Args:
        **kwargs: Context variables to bind (user_id, request_id, etc.)
        
    Assumptions:
    - Context persists for current execution context
    - Useful for binding user_id and request_id per-request
    """
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear all bound context variables.
    
    Assumptions:
    - Should be called at end of request
    """
    structlog.contextvars.clear_contextvars()


# Configure logging on module import
configure_logging()
