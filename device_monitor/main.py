"""Main entry point for Device monitoring service."""
import logging
import sys

from .config import device_config, log_config_status
from .api_server import run_server


def configure_logging():
    logging.basicConfig(
        level=getattr(logging, device_config.log_level.upper(), logging.INFO),
        format='%(asctime)s %(levelname)s %(name)s - %(message)s'
    )


def main():
    configure_logging()
    log_config_status()

    if device_config.missing_required:
        logging.error(
            "[Device Monitor] Missing required configuration: %s",
            ", ".join(device_config.missing_required)
        )
        logging.error("[Device Monitor] Please check your .env file")
        return 1

    logging.info("[Device Monitor] Starting Device monitoring service")

    try:
        run_server()
    except KeyboardInterrupt:
        logging.info("[Device Monitor] Shutdown requested (KeyboardInterrupt). Exiting.")
    except Exception as e:
        logging.exception("[Device Monitor] Fatal error: %s", e)
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
