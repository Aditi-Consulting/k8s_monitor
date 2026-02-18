import logging
import sys
from k8s_monitor.monitor import K8sMonitor
from k8s_monitor.config import config, log_config_status


def configure_logging():
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format='%(asctime)s %(levelname)s %(name)s - %(message)s'
    )


def main():
    configure_logging()
    log_config_status()
    logging.info("Starting Kubernetes monitoring service")
    monitor = K8sMonitor()
    try:
        monitor.run_forever()
    except KeyboardInterrupt:
        logging.info("Shutdown requested (KeyboardInterrupt). Exiting.")
    except Exception as e:
        logging.exception("Fatal error: %s", e)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
