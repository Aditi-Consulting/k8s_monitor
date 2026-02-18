"""Client to call external Spring Boot application and capture exceptions."""
from __future__ import annotations

import logging
import requests
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import splunk_config

logger = logging.getLogger(__name__)

@dataclass
class ApplicationException:
    """Exception details from external application."""
    timestamp: str
    status: int
    error: str
    message: str
    path: str
    code: Optional[str] = None
    location: Optional[str] = None
    context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "status": self.status,
            "error": self.error,
            "message": self.message,
            "path": self.path,
            "code": self.code,
            "location": self.location,
            "context": self.context
        }


class ExternalAPIClient:
    """Makes GET calls to external Spring Boot application endpoint."""

    def __init__(self):
        self.base_url = splunk_config.external_app_url
        self.endpoint = splunk_config.external_app_endpoint
        self.timeout = splunk_config.external_app_timeout

    def call_external_api(self) -> Optional[ApplicationException]:
        """
        Make GET call to external Spring Boot endpoint.
        Returns ApplicationException if exception occurs, None if successful (unlikely).
        """
        url = f"{self.base_url}{self.endpoint}"

        logger.info("[Splunk Monitor] [API Client] Calling external API: %s", url)
        logger.info("[Splunk Monitor] [API Client] Hitting endpoint: GET %s", url)
        logger.debug("[Splunk Monitor] [API Client] Timeout configured: %s seconds", self.timeout)

        try:
            resp = requests.get(url, timeout=self.timeout)

            logger.info("[Splunk Monitor] [API Client] Response received: status=%s content_length=%s",
                       resp.status_code, len(resp.content))

            # Spring Boot error response structure
            if resp.status_code >= 400:
                logger.warning("[Splunk Monitor] [API Client] HTTP error detected: status=%s", resp.status_code)
                return self._parse_spring_boot_error(resp)

            # Successful response (shouldn't happen for our test endpoint)
            logger.info("[Splunk Monitor] [API Client] API call successful (no exception)")
            return None

        except requests.exceptions.Timeout:
            logger.error("[Splunk Monitor] [API Client] Request timeout after %s seconds to %s", self.timeout, url)
            return ApplicationException(
                timestamp=datetime.now(timezone.utc).isoformat(),
                status=0,
                error="TimeoutError",
                message=f"Request timeout after {self.timeout} seconds to {url}",
                path=self.endpoint
            )

        except requests.exceptions.ConnectionError as e:
            logger.error("[Splunk Monitor] [API Client] Connection error to %s: %s", url, str(e))
            return ApplicationException(
                timestamp=datetime.now(timezone.utc).isoformat(),
                status=0,
                error="ConnectionError",
                message=f"Failed to connect to {url}. Ensure the application is running. Error: {str(e)}",
                path=self.endpoint
            )

        except requests.exceptions.RequestException as e:
            logger.error("[Splunk Monitor] [API Client] Request error to %s: %s", url, str(e))
            return ApplicationException(
                timestamp=datetime.now(timezone.utc).isoformat(),
                status=0,
                error="RequestError",
                message=f"Request failed to {url}: {str(e)}",
                path=self.endpoint
            )

        except Exception as e:
            logger.exception("[Splunk Monitor] [API Client] Unexpected error calling %s", url)
            return ApplicationException(
                timestamp=datetime.now(timezone.utc).isoformat(),
                status=0,
                error=type(e).__name__,
                message=f"Unexpected error: {str(e)}",
                path=self.endpoint
            )

    def _parse_spring_boot_error(self, resp: requests.Response) -> ApplicationException:
        """Parse Spring Boot standard error response format."""
        logger.debug("[Splunk Monitor] [API Client] Parsing Spring Boot error response")
        try:
            data = resp.json()

            # Extract message field (the actual error description)
            message = data.get('message', '')
            if not message:
                # Fallback to response text if message field is empty
                message = resp.text[:500]

            logger.debug("[Splunk Monitor] [API Client] Parsed JSON error: type=%s status=%s",
                         data.get('error'), data.get('status'))
            logger.info("[Splunk Monitor] [API Client] Extracted message: %s", message[:200])

            return ApplicationException(
                timestamp=data.get('timestamp', datetime.now(timezone.utc).isoformat()),
                status=data.get('status', resp.status_code),
                error=data.get('error', 'Unknown Error'),
                message=message,  # ✅ Now contains actual error message
                path=data.get('path', self.endpoint),
                code=data.get('code'),
                location=data.get('location'),
                context=data.get('context')
            )
        except ValueError as e:
            # Response is not JSON
            logger.warning("[Splunk Monitor] [API Client] Non-JSON error response: %s", str(e))
            return ApplicationException(
                timestamp=datetime.now(timezone.utc).isoformat(),
                status=resp.status_code,
                error="HTTPError",
                message=f"HTTP {resp.status_code}: {resp.text[:500]}",
                path=self.endpoint
            )


external_api_client = ExternalAPIClient()
