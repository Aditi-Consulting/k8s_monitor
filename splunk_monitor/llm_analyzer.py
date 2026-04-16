"""LLM analyzer using OpenAI GPT-4o-mini to generate alert messages."""
from __future__ import annotations

import logging
import re
from typing import Dict, Any
from openai import AzureOpenAI, OpenAI

from .config import splunk_config
from .api_client import ApplicationException

logger = logging.getLogger(__name__)


class LLMAnalyzer:
    """Analyzes Spring Boot exceptions and generates clean alert signals."""

    def __init__(self):
        if not splunk_config.is_openai_configured:
            logger.warning(
                "[Splunk Monitor] OpenAI API key not configured; LLM analysis will be disabled"
            )
            self.client = None
        elif splunk_config.azure_openai_endpoint:
            self.client = AzureOpenAI(
                api_key=splunk_config.openai_api_key,
                azure_endpoint=splunk_config.azure_openai_endpoint,
                api_version=splunk_config.azure_openai_api_version,
            )
        else:
            self.client = OpenAI(api_key=splunk_config.openai_api_key)

        self.model = splunk_config.openai_model
        self.timeout = splunk_config.openai_timeout

    def analyze_exception(self, exception: ApplicationException) -> Dict[str, Any]:
        """
        Generate a clean, single-line alert signal with retry logic.
        Returns dict with: severity, alert_message, analysis_source, model, fallback_reason
        """
        severity = self._determine_basic_severity(exception)

        if not self.client:
            logger.warning("[Splunk Monitor] ⚠️ LLM analysis skipped (not configured) — using fallback")
            return self._fallback_analysis(exception, severity, "LLM not configured")

        # Try LLM with retries (ensure it always works)
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                prompt = self._build_analysis_prompt(exception)

                logger.info(
                    "[Splunk Monitor] Sending exception to LLM (attempt %d/%d, model=%s, timeout=%ds)",
                    attempt, max_retries, self.model, self.timeout
                )

                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are an automated alert signal generator for an AIOps platform. "
                                "Your job is to generate a SINGLE, concise alert signal that can be reliably deduplicated, "
                                "classified by downstream AI agents, and used for automated remediation workflows. "
                                "IMPORTANT RULES: Do NOT perform root cause analysis. Do NOT suggest resolution steps. "
                                "Do NOT describe business or user impact. Do NOT write explanations or narratives. "
                                "Do NOT invent any details. Your output MUST be ONE sentence only, start EXACTLY with 'Alert:', "
                                "describe the failure type and affected component, use precise technical terms, and be stable "
                                "across deployments. You are generating a SIGNAL, not an analysis."
                            )
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=0.1,
                    max_tokens=150,
                    timeout=self.timeout
                )

                alert_message = response.choices[0].message.content.strip()

                # Enforce single-line constraint
                if "\n" in alert_message:
                    logger.warning("[Splunk Monitor] LLM generated multi-line output, truncating to first line")
                    alert_message = alert_message.split("\n")[0]

                # Enforce max length (prevent verbosity)
                if len(alert_message) > 200:
                    logger.warning("[Splunk Monitor] LLM output too long (%d chars), truncating", len(alert_message))
                    alert_message = alert_message[:197] + "..."

                # Ensure "Alert:" prefix
                if not alert_message.startswith("Alert:"):
                    alert_message = f"Alert: {alert_message}"

                logger.info("[Splunk Monitor] ✅ LLM alert generated successfully (attempt %d): %s", attempt, alert_message[:100])

                return {
                    "alert_message": alert_message,
                    "severity": severity,
                    "analysis_source": "LLM",
                    "model": self.model,
                    "fallback_reason": None,
                    "llm_attempts": attempt
                }

            except Exception as e:
                error_msg = str(e)
                logger.warning(
                    "[Splunk Monitor] ⚠️ LLM attempt %d/%d failed: %s",
                    attempt, max_retries, error_msg
                )

                # If not last attempt, retry after short delay
                if attempt < max_retries:
                    import time
                    retry_delay = attempt * 2  # 2s, 4s, 6s backoff
                    logger.info("[Splunk Monitor] Retrying in %d seconds...", retry_delay)
                    time.sleep(retry_delay)
                    continue

                # All retries exhausted - use fallback
                logger.error("[Splunk Monitor] ❌ LLM failed after %d attempts, using fallback", max_retries)

                if "timeout" in error_msg.lower():
                    fallback_reason = f"LLM timeout after {max_retries} attempts"
                elif "rate" in error_msg.lower():
                    fallback_reason = f"Rate limit exceeded ({max_retries} attempts)"
                elif "authentication" in error_msg.lower() or "api key" in error_msg.lower():
                    fallback_reason = "Authentication failed - check API key"
                else:
                    fallback_reason = f"LLM error after {max_retries} attempts: {error_msg[:100]}"

                return self._fallback_analysis(exception, severity, fallback_reason)

    def _build_analysis_prompt(self, exception: ApplicationException) -> str:
        """Build prompt for generating concise alert signals."""

        # Build context string
        context_str = ""
        if exception.context:
            ctx_parts = []
            for key, value in exception.context.items():
                ctx_parts.append(f"{key}: {value}")
            context_str = "\n".join(ctx_parts)

        # Simplify location
        simplified_location = self._simplify_location(exception.location) if exception.location else "unknown"

        # Build error data section
        error_data_parts = ["ERROR DATA:", f"Error Type: {exception.error}"]

        if exception.code:
            error_data_parts.append(f"Error Code: {exception.code}")

        error_data_parts.append(f"Message: {exception.message}")

        if exception.location:
            error_data_parts.append(f"Location (class.method): {simplified_location}")

        error_data_parts.extend([
            f"HTTP Status: {exception.status}",
            f"Endpoint: {exception.path}"
        ])

        if context_str:
            error_data_parts.extend(["", "ADDITIONAL CONTEXT:", context_str])

        error_data = "\n".join(error_data_parts)

        return f"""Generate a single-line alert signal based ONLY on the error data below.

REQUIREMENTS:
1. Start exactly with: "Alert:"
2. ONE sentence only
3. Mention:
   - failure type (exception or error)
   - affected service or component
4. Do NOT include:
   - remediation steps
   - impact analysis
   - opinions
   - explanations
5. Do NOT invent missing data

{error_data}

Generate the alert signal now:
"""

    def _fallback_analysis(
        self,
        exception: ApplicationException,
        severity: str,
        fallback_reason: str = "Unknown"
    ) -> Dict[str, Any]:
        """
        Deterministic fallback when LLM is unavailable.
        Format is intentionally different from LLM (with [FALLBACK] prefix) to make failure obvious.
        """
        logger.warning("[Splunk Monitor] 🔧 FALLBACK MODE ACTIVATED: %s", fallback_reason)

        message = exception.message
        message_lower = message.lower()
        error_code = exception.code or ""
        location = exception.location or ""

        # Extract simplified location
        simplified_location = self._simplify_location(location) if location else "unknown"

        # Build BASIC alert with [FALLBACK] prefix to make it obvious
        if error_code == "NULL_POINTER_EXCEPTION":
            alert_message = f"Alert: [FALLBACK] NullPointerException in {simplified_location}"
        elif "database" in message_lower or "jdbc" in message_lower:
            alert_message = f"Alert: [FALLBACK] Database connection failure in {simplified_location or 'application'}"
        elif "timeout" in message_lower:
            alert_message = f"Alert: [FALLBACK] Request timeout at {exception.path}"
        elif exception.error == "ConnectionError":
            alert_message = f"Alert: [FALLBACK] Network connectivity failure for {exception.path}"
        elif exception.status >= 500:
            alert_message = f"Alert: [FALLBACK] {exception.error} in {simplified_location or 'application'}"
        else:
            alert_message = f"Alert: [FALLBACK] {exception.error} at {exception.path}"

        logger.warning("[Splunk Monitor] 🔧 Fallback alert generated: %s (Reason: %s)", alert_message, fallback_reason)

        return {
            "alert_message": alert_message,
            "severity": severity,
            "analysis_source": "FALLBACK",
            "model": None,
            "fallback_reason": fallback_reason,
            "llm_attempts": 0
        }

    @staticmethod
    def _simplify_location(location: str) -> str:
        """Extract Service.method from full qualified path.

        Example: com.ai_ops.demo.service.UserService.getAllUsers:35 -> UserService.getAllUsers
        """
        if not location:
            return "unknown"

        # Remove line numbers
        location_without_line = location.split(":")[0]

        # Split by dots
        parts = location_without_line.split(".")
        if len(parts) >= 2:
            service = parts[-2]  # e.g., UserService
            method = parts[-1]   # e.g., getAllUsers
            return f"{service}.{method}"

        return location_without_line

    @staticmethod
    def _extract_db_entities(message: str) -> str:
        """Extract host:port and optional db name from JDBC URL or similar in message."""
        # jdbc:postgresql://host:port/dbname or host:port or host.domain:5432
        jdbc_match = re.search(
            r"jdbc:postgresql://([^:/]+(?::\d+)?(?:/[^\s]+)?)",
            message,
            re.IGNORECASE
        )
        if jdbc_match:
            part = jdbc_match.group(1).strip()
            # Normalize: host:port/db -> host:port (db)
            if "/" in part:
                host_port, db = part.rsplit("/", 1)
                db = db.split("?")[0].strip()
                return f"{host_port} ({db})"
            return part
        # Fallback: hostname:port pattern
        host_port = re.search(r"([a-zA-Z0-9][a-zA-Z0-9.-]+\.(?:internal|local)|localhost):(\d+)", message)
        if host_port:
            return f"{host_port.group(1)}:{host_port.group(2)}"
        return ""

    @staticmethod
    def _determine_basic_severity(exception: ApplicationException) -> str:
        """Basic severity determination without classification logic."""
        if exception.status >= 500 or exception.error in {"ConnectionError", "TimeoutError"}:
            return "high"
        elif exception.status >= 400:
            return "medium"
        return "low"


llm_analyzer = LLMAnalyzer()
