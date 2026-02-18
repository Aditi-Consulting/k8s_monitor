"""Configuration management for the Kubernetes monitoring service.
Loads environment variables (optionally from a .env file) and exposes a Config dataclass.
"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Resolve possible env files
_root = Path(__file__).resolve().parent.parent
_env_path = _root / '.env'
_loaded_file: str | None = None

# Load precedence: .env > existing process env
if _env_path.exists():
    load_dotenv(_env_path)
    _loaded_file = str(_env_path)
else:
    # load current working directory default if present
    load_dotenv()

@dataclass(frozen=True)
class Config:
    smtp_host: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    email_user: str = os.getenv("EMAIL_USER", "")
    email_pass: str = os.getenv("EMAIL_PASS", "")
    email_sender: str = os.getenv("EMAIL_SENDER", os.getenv("EMAIL_USER", ""))
    email_receiver: str = os.getenv("EMAIL_RECEIVER", os.getenv("EMAIL_USER", ""))
    poll_interval_seconds: int = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))
    kube_context: str | None = os.getenv("KUBE_CONTEXT")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    max_email_body_length: int = int(os.getenv("MAX_EMAIL_BODY_LENGTH", "4000"))
    # Default to False so we send the first snapshot email unless explicitly disabled
    skip_initial_email: bool = os.getenv("SKIP_INITIAL_EMAIL", "false").lower() in {"1","true","yes"}

    # Alerting settings
    alert_api_url: str = os.getenv("ALERT_API_URL", "http://localhost:3002/api/v1/alerts")
    alerts_enabled: bool = os.getenv("ALERTS_ENABLED", "true").lower() in {"1","true","yes"}
    min_replicas_threshold: int = int(os.getenv("MIN_REPLICAS_THRESHOLD", "5"))
    alert_created_by: str = os.getenv("ALERT_CREATED_BY", "K8s_monitor")
    alert_timeout_seconds: int = int(os.getenv("ALERT_TIMEOUT_SECONDS", "10"))  # creation
    classification_timeout_seconds: int = int(os.getenv("CLASSIFICATION_TIMEOUT_SECONDS", "30"))  # allow longer LLM processing
    task_agent_timeout_seconds: int = int(os.getenv("TASK_AGENT_TIMEOUT_SECONDS", "60"))  # solving may take longer

    @property
    def is_email_configured(self) -> bool:
        return not self.missing_required

    @property
    def missing_required(self) -> list[str]:
        missing = []
        if not self.email_user: missing.append("EMAIL_USER")
        if not self.email_pass: missing.append("EMAIL_PASS")
        if not self.email_receiver: missing.append("EMAIL_RECEIVER")
        return missing

config = Config()

def log_config_status():
    # Mask password length only
    masked_pass = f"len={len(config.email_pass)}" if config.email_pass else "<empty>"
    logger.info(
        "Config loaded (source=%s) smtp_host=%s smtp_port=%s email_user=%s email_receiver=%s email_pass(%s) poll_interval=%s skip_initial_email=%s alerts_enabled=%s min_replicas_threshold=%s alert_api_url=%s",
        _loaded_file or "<process env>", config.smtp_host, config.smtp_port,
        config.email_user or "<empty>", config.email_receiver or "<empty>", masked_pass,
        config.poll_interval_seconds, config.skip_initial_email,
        config.alerts_enabled, config.min_replicas_threshold, config.alert_api_url
    )
    if config.missing_required:
        logger.warning("Missing required email variables: %s", ", ".join(config.missing_required))
    else:
        logger.info("Email configuration looks complete.")
