"""Client to call external device application and capture exceptions.

=======================================================================
NOTE: This module is NOT used in the current device monitoring usecase.
The /fetch-devices endpoint directly creates a hardcoded alert message
("Alert : Unlock the Device: IMEI<number>") without calling any
external API or processing external exceptions.

This file is kept as a placeholder for future extensibility — if the
device usecase later requires calling an external device management API
to detect exceptions before creating alerts, this module can be
uncommented and adapted.
=======================================================================
"""
from __future__ import annotations

import logging
# import requests
# from typing import Optional, Dict, Any
# from dataclasses import dataclass
# from datetime import datetime, timezone
#
# from .config import device_config

logger = logging.getLogger(__name__)


# @dataclass
# class DeviceException:
#     """Exception details from external device application."""
#     timestamp: str
#     status: int
#     error: str
#     message: str
#     path: str
#     code: Optional[str] = None
#     location: Optional[str] = None
#     context: Optional[Dict[str, Any]] = None
#
#     def to_dict(self) -> Dict[str, Any]:
#         return {
#             "timestamp": self.timestamp,
#             "status": self.status,
#             "error": self.error,
#             "message": self.message,
#             "path": self.path,
#             "code": self.code,
#             "location": self.location,
#             "context": self.context,
#         }


# class ExternalAPIClient:
#     """Makes GET calls to external device application endpoint."""
#
#     def __init__(self):
#         self.base_url = device_config.external_app_url
#         self.endpoint = device_config.external_app_endpoint
#         self.timeout = device_config.external_app_timeout
#
#     def call_external_api(self) -> Optional[DeviceException]:
#         """
#         Make GET call to external device endpoint.
#         Returns DeviceException if exception occurs, None if successful.
#         """
#         url = f"{self.base_url}{self.endpoint}"
#
#         logger.info("[Device Monitor] [API Client] Calling external API: %s", url)
#
#         try:
#             resp = requests.get(url, timeout=self.timeout)
#
#             if resp.status_code >= 400:
#                 logger.warning("[Device Monitor] [API Client] HTTP error: status=%s", resp.status_code)
#                 return self._parse_error_response(resp)
#
#             logger.info("[Device Monitor] [API Client] API call successful (no exception)")
#             return None
#
#         except requests.exceptions.Timeout:
#             logger.error("[Device Monitor] [API Client] Timeout after %s seconds", self.timeout)
#             return DeviceException(
#                 timestamp=datetime.now(timezone.utc).isoformat(),
#                 status=0,
#                 error="TimeoutError",
#                 message=f"Request timeout after {self.timeout} seconds to {url}",
#                 path=self.endpoint,
#             )
#
#         except requests.exceptions.ConnectionError as e:
#             logger.error("[Device Monitor] [API Client] Connection error: %s", e)
#             return DeviceException(
#                 timestamp=datetime.now(timezone.utc).isoformat(),
#                 status=0,
#                 error="ConnectionError",
#                 message=f"Failed to connect to {url}: {e}",
#                 path=self.endpoint,
#             )
#
#         except Exception as e:
#             logger.exception("[Device Monitor] [API Client] Unexpected error calling %s", url)
#             return DeviceException(
#                 timestamp=datetime.now(timezone.utc).isoformat(),
#                 status=0,
#                 error=type(e).__name__,
#                 message=f"Unexpected error: {e}",
#                 path=self.endpoint,
#             )
#
#     def _parse_error_response(self, resp: requests.Response) -> DeviceException:
#         """Parse error response into DeviceException."""
#         try:
#             data = resp.json()
#             return DeviceException(
#                 timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
#                 status=data.get("status", resp.status_code),
#                 error=data.get("error", "Unknown Error"),
#                 message=data.get("message", resp.text[:500]),
#                 path=data.get("path", self.endpoint),
#                 code=data.get("code"),
#                 location=data.get("location"),
#                 context=data.get("context"),
#             )
#         except ValueError:
#             return DeviceException(
#                 timestamp=datetime.now(timezone.utc).isoformat(),
#                 status=resp.status_code,
#                 error="HTTPError",
#                 message=f"HTTP {resp.status_code}: {resp.text[:500]}",
#                 path=self.endpoint,
#             )
#
#
# external_api_client = ExternalAPIClient()
