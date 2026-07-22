# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Configuration management for Loobric.

This module handles application configuration from environment variables.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.
    
    Assumptions:
    - Environment variables override defaults
    - API version is configurable
    - AUTH_ENABLED can be disabled for testing/development
    """
    
    # Authentication
    auth_enabled: bool = True
    
    # Database
    database_url: str = "sqlite:///./loobric.db"

    # Media blob store: where canonical media bytes (3D models, drawings, images)
    # live on disk, content-addressed. The record carries only a reference; the
    # bytes are served out-of-band (see docs/TOOL_SCHEMA.md §Media). Back this
    # directory up alongside the database.
    media_dir: str = "./loobric_server_media"
    
    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_version: str = "v1"
    
    # MQTT
    mqtt_enabled: bool = False
    mqtt_broker: str = "localhost"
    mqtt_port: int = 1883
    
    # Logging
    log_level: str = "INFO"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False
    )


settings = Settings()
