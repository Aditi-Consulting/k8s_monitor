"""LLM analyzer for device exceptions using OpenAI.

=======================================================================
NOTE: This module is NOT used in the current device monitoring usecase.
The alert message is hardcoded ("Alert : Unlock the Device: IMEI<number>")
and does not require LLM-based analysis or severity determination.

This file is kept as a placeholder for future extensibility — if the
device usecase later requires intelligent analysis of device exceptions
(e.g., analyzing device logs, diagnosing hardware failures, etc.),
this module can be uncommented and adapted.
=======================================================================
"""
from __future__ import annotations

import logging
# import re
# from typing import Dict, Any
# from openai import OpenAI
#
# from .config import device_config

logger = logging.getLogger(__name__)


# class LLMAnalyzer:
#     """Analyzes device exceptions and generates clean alert signals."""
#
#     def __init__(self):
#         if not device_config.openai_api_key:
#             logger.warning(
#                 "[Device Monitor] OpenAI API key not configured; LLM analysis will be disabled"
#             )
#             self.client = None
#         else:
#             self.client = OpenAI(api_key=device_config.openai_api_key)
#
#         self.model = device_config.openai_model
#         self.timeout = device_config.openai_timeout
#
#     def analyze_exception(self, exception) -> Dict[str, Any]:
#         """
#         Generate a clean, single-line alert signal with retry logic.
#         Returns dict with: severity, alert_message, analysis_source, model, fallback_reason
#         """
#         severity = self._determine_basic_severity(exception)
#
#         if not self.client:
#             logger.warning("[Device Monitor] ⚠️ LLM analysis skipped (not configured) — using fallback")
#             return self._fallback_analysis(exception, severity, "LLM not configured")
#
#         max_retries = 3
#         for attempt in range(1, max_retries + 1):
#             try:
#                 prompt = self._build_analysis_prompt(exception)
#
#                 logger.info(
#                     "[Device Monitor] Sending exception to LLM (attempt %d/%d, model=%s, timeout=%ds)",
#                     attempt, max_retries, self.model, self.timeout,
#                 )
#
#                 response = self.client.chat.completions.create(
#                     model=self.model,
#                     messages=[
#                         {
#                             "role": "system",
#                             "content": (
#                                 "You are an automated alert signal generator for an AIOps platform. "
#                                 "Your job is to generate a SINGLE, concise alert signal for device issues. "
#                                 "Your output MUST be ONE sentence only, start EXACTLY with 'Alert:', "
#                                 "describe the failure type and affected device, use precise technical terms."
#                             ),
#                         },
#                         {"role": "user", "content": prompt},
#                     ],
#                     temperature=0.1,
#                     max_tokens=150,
#                     timeout=self.timeout,
#                 )
#
#                 alert_message = response.choices[0].message.content.strip()
#
#                 # Enforce single-line
#                 if "\n" in alert_message:
#                     alert_message = alert_message.split("\n")[0]
#
#                 # Enforce max length
#                 if len(alert_message) > 200:
#                     alert_message = alert_message[:197] + "..."
#
#                 # Ensure "Alert:" prefix
#                 if not alert_message.startswith("Alert:"):
#                     alert_message = f"Alert: {alert_message}"
#
#                 logger.info("[Device Monitor] ✅ LLM alert generated (attempt %d): %s", attempt, alert_message[:100])
#
#                 return {
#                     "alert_message": alert_message,
#                     "severity": severity,
#                     "analysis_source": "LLM",
#                     "model": self.model,
#                     "fallback_reason": None,
#                     "llm_attempts": attempt,
#                 }
#
#             except Exception as e:
#                 logger.warning("[Device Monitor] ⚠️ LLM attempt %d/%d failed: %s", attempt, max_retries, e)
#                 if attempt < max_retries:
#                     import time
#                     time.sleep(attempt * 2)
#                     continue
#                 logger.error("[Device Monitor] ❌ LLM failed after %d attempts, using fallback", max_retries)
#                 return self._fallback_analysis(exception, severity, f"LLM error: {e}")
#
#     def _build_analysis_prompt(self, exception) -> str:
#         """Build prompt for generating concise device alert signals."""
#         return f"""Generate a single-line alert signal based ONLY on the error data below.
#
# REQUIREMENTS:
# 1. Start exactly with: "Alert:"
# 2. ONE sentence only
# 3. Mention failure type and affected device/component
# 4. Do NOT include remediation steps or impact analysis
#
# ERROR DATA:
# Error Type: {exception.error}
# Message: {exception.message}
# HTTP Status: {exception.status}
# Endpoint: {exception.path}
#
# Generate the alert signal now:
# """
#
#     def _fallback_analysis(self, exception, severity: str, fallback_reason: str) -> Dict[str, Any]:
#         """Deterministic fallback when LLM is unavailable."""
#         return {
#             "alert_message": f"Alert: [FALLBACK] Device error at {exception.path} - {exception.message}",
#             "severity": severity,
#             "analysis_source": "FALLBACK",
#             "model": None,
#             "fallback_reason": fallback_reason,
#             "llm_attempts": 0,
#         }
#
#     @staticmethod
#     def _determine_basic_severity(exception) -> str:
#         """Basic severity determination without LLM."""
#         if exception.status >= 500 or exception.error in {"ConnectionError", "TimeoutError"}:
#             return "high"
#         elif exception.status >= 400:
#             return "medium"
#         return "low"
#
#
# llm_analyzer = LLMAnalyzer()
