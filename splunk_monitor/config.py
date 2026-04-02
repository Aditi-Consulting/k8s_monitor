"""Configuration management for Splunk monitoring service."""
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
class SplunkConfig:
    # External Spring Boot app configuration
    external_app_url: str = os.getenv("EXTERNAL_APP_URL", "http://host.docker.internal:9090")
    external_app_endpoint: str = os.getenv("EXTERNAL_APP_ENDPOINT", "/api/users")
    external_app_timeout: int = int(os.getenv("EXTERNAL_APP_TIMEOUT", "30"))

    # Flask server configuration
    flask_host: str = os.getenv("SPLUNK_FLASK_HOST", "0.0.0.0")
    flask_port: int = int(os.getenv("SPLUNK_FLASK_PORT", "5001"))
    flask_debug: bool = os.getenv("SPLUNK_FLASK_DEBUG", "false").lower() in {"1", "true", "yes"}

    # OpenAI configuration
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    openai_timeout: int = int(os.getenv("OPENAI_TIMEOUT", "30"))  # Increased from 10 to 30 seconds

    # Alert API configuration (same as k8s)
    alert_api_url: str = os.getenv("ALERT_API_URL", "http://localhost:3002/api/v1/alerts")
    alert_created_by: str = os.getenv("SPLUNK_ALERT_CREATED_BY", "Splunk_Monitor")
    alert_timeout_seconds: int = int(os.getenv("ALERT_TIMEOUT_SECONDS", "5"))
    classification_timeout_seconds: int = int(os.getenv("CLASSIFICATION_TIMEOUT_SECONDS", "10"))
    task_agent_timeout_seconds: int = int(os.getenv("TASK_AGENT_TIMEOUT_SECONDS", "15"))

    # Splunk task agent URL (custom, direct call instead of going through api-service)
    splunk_task_agent_url: str = os.getenv("SPLUNK_TASK_AGENT_URL", "http://host.docker.internal:5004/api/v1/splunk-agent")

    # Email settings (reuse from k8s_monitor)
    email_user: str = os.getenv("EMAIL_USER", "")
    email_receiver: str = os.getenv("EMAIL_RECEIVER", "")

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    @property
    def is_openai_configured(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def is_email_configured(self) -> bool:
        return bool(self.email_user) and bool(self.email_receiver)

    @property
    def missing_required(self) -> list[str]:
        missing = []
        if not self.openai_api_key or self.openai_api_key == "your-openai-api-key-here":
            missing.append("OPENAI_API_KEY")
        if not self.external_app_url:
            missing.append("EXTERNAL_APP_URL")
        if not self.alert_api_url:
            missing.append("ALERT_API_URL")
        return missing

splunk_config = SplunkConfig()

def log_config_status():
    masked_key = f"sk-...{splunk_config.openai_api_key[-4:]}" if splunk_config.openai_api_key else "<empty>"
    logger.info(
        "[Splunk Monitor] Config loaded: external_app_url=%s flask_port=%s openai_model=%s openai_api_key=%s alert_api_url=%s",
        splunk_config.external_app_url,
        splunk_config.flask_port,
        splunk_config.openai_model,
        masked_key,
        splunk_config.alert_api_url
    )
    if splunk_config.missing_required:
        logger.warning("[Splunk Monitor] Missing required variables: %s", ", ".join(splunk_config.missing_required))
    else:
        logger.info("[Splunk Monitor] Configuration looks complete.")

