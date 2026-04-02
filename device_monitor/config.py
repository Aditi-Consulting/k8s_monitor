"""Configuration management for Device monitoring service."""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env file
_root = Path(__file__).resolve().parent.parent
_env_path = _root / '.env'

if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()


@dataclass(frozen=True)
class DeviceConfig:
    # Flask server configuration
    flask_host: str = os.getenv("DEVICE_FLASK_HOST", "0.0.0.0")
    flask_port: int = int(os.getenv("DEVICE_FLASK_PORT", "5003"))
    flask_debug: bool = os.getenv("DEVICE_FLASK_DEBUG", "false").lower() in {"1", "true", "yes"}

    # Device IMEI (attached to every alert message)
    device_imei: str = os.getenv("DEVICE_IMEI", "")

    # Alert API configuration (same base as k8s/splunk)
    alert_api_url: str = os.getenv("ALERT_API_URL", "http://localhost:3002/api/v1/alerts")
    alert_created_by: str = os.getenv("DEVICE_ALERT_CREATED_BY", "Device_Monitor")
    alert_timeout_seconds: int = int(os.getenv("DEVICE_ALERT_TIMEOUT_SECONDS", "30"))
    classification_timeout_seconds: int = int(os.getenv("DEVICE_CLASSIFICATION_TIMEOUT_SECONDS", "120"))
    task_agent_timeout_seconds: int = int(os.getenv("DEVICE_TASK_AGENT_TIMEOUT_SECONDS", "300"))

    # Task agent unlock URL (device usecase uses a different URL from standard task agent)
    # Uses host.docker.internal because this service runs in Docker and unlock API runs on host
    task_agent_unlock_url: str = os.getenv("DEVICE_TASK_AGENT_UNLOCK_URL", "http://host.docker.internal:8888/api/v1/unlock")

    # Email settings (reuse from k8s_monitor emailer)
    email_user: str = os.getenv("EMAIL_USER", "")
    email_receiver: str = os.getenv("EMAIL_RECEIVER", "")

    # -----------------------------------------------------------------------
    # LLM / OpenAI configuration
    # NOTE: Not used in the current device usecase. The alert message is
    #       hardcoded ("Alert : Unlock the Device: IMEI<number>").
    #       Kept here for future extensibility if LLM-based analysis is needed.
    # -----------------------------------------------------------------------
    # openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    # openai_model: str = os.getenv("DEVICE_OPENAI_MODEL", "gpt-4o-mini")
    # openai_timeout: int = int(os.getenv("DEVICE_OPENAI_TIMEOUT", "60"))

    # -----------------------------------------------------------------------
    # External device API configuration
    # NOTE: Not used in the current device usecase. The /fetch-devices
    #       endpoint directly creates alerts without calling an external API.
    #       Kept here for future extensibility.
    # -----------------------------------------------------------------------
    # external_app_url: str = os.getenv("DEVICE_EXTERNAL_APP_URL", "")
    # external_app_endpoint: str = os.getenv("DEVICE_EXTERNAL_APP_ENDPOINT", "")
    # external_app_timeout: int = int(os.getenv("DEVICE_EXTERNAL_APP_TIMEOUT", "30"))

    # Logging
    log_level: str = os.getenv("DEVICE_LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO"))

    @property
    def is_email_configured(self) -> bool:
        return bool(self.email_user) and bool(self.email_receiver)

    @property
    def missing_required(self) -> list[str]:
        missing = []
        if not self.alert_api_url:
            missing.append("ALERT_API_URL")
        if not self.device_imei:
            missing.append("DEVICE_IMEI")
        return missing


device_config = DeviceConfig()


def log_config_status():
    logger.info(
        "[Device Monitor] Config loaded: flask=%s:%s device_imei=%s alert_api_url=%s "
        "task_agent_unlock_url=%s alert_created_by=%s log_level=%s",
        device_config.flask_host, device_config.flask_port,
        device_config.device_imei or "<empty>",
        device_config.alert_api_url,
        device_config.task_agent_unlock_url,
        device_config.alert_created_by,
        device_config.log_level,
    )
    if device_config.missing_required:
        logger.warning("[Device Monitor] Missing required variables: %s", ", ".join(device_config.missing_required))
    else:
        logger.info("[Device Monitor] Configuration looks complete.")
