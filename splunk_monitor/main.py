"""Main entry point for Splunk monitoring service."""
import logging
import sys

from .config import splunk_config, log_config_status
from .api_server import run_server

def configure_logging():
    logging.basicConfig(
        level=getattr(logging, splunk_config.log_level.upper(), logging.INFO),
        format='%(asctime)s %(levelname)s %(name)s - %(message)s'
    )

def main():
    configure_logging()
    log_config_status()

    if splunk_config.missing_required:
        logging.error(
            "[Splunk Monitor] Missing required configuration: %s",
            ", ".join(splunk_config.missing_required)
        )
        logging.error("[Splunk Monitor] Please check your .env file")
        return 1

    logging.info("[Splunk Monitor] Starting Splunk monitoring service")

    try:
        run_server()
    except KeyboardInterrupt:
        logging.info("[Splunk Monitor] Shutdown requested (KeyboardInterrupt). Exiting.")
    except Exception as e:
        logging.exception("[Splunk Monitor] Fatal error: %s", e)
        return 1

    return 0

if __name__ == '__main__':
    sys.exit(main())

