"""Flask API server for Device monitoring with /fetch-devices endpoint.

When /fetch-devices is hit:
  1. Build hardcoded alert message using IMEI from config
  2. Create alert via 3-stage flow (create → classify → unlock)
  3. Send email notification
  4. Return JSON response
"""
from __future__ import annotations

import logging
import threading
from flask import Flask, jsonify

from .config import device_config
from .alert_creator import alert_creator
from k8s_monitor.emailer import emailer

logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.route('/fetch-devices', methods=['GET', 'POST'])
def trigger_device_unlock():
    """
    Endpoint to trigger device unlock alert flow.

    Workflow:
    1. Build alert message: "Alert : Unlock the Device: IMEI<config_value>"
    2. Create alert (create -> classify -> unlock)
    3. Send email notification
    """
    logger.info("[Device Monitor] ========== Received /fetch-devices request ==========")

    imei = device_config.device_imei
    if not imei:
        logger.error("[Device Monitor] DEVICE_IMEI not configured — cannot create alert")
        return jsonify({
            "success": False,
            "alert_created": False,
            "email_sent": False,
            "message": "DEVICE_IMEI not configured",
        }), 500

    alert_message = f"Alert : Unlock the Device: IMEI{imei}"
    logger.info("[Device Monitor] Alert message: %s", alert_message)

    # Step 1: Create alert (Stage 1 only — return immediately)
    try:
        logger.info("[Device Monitor] Step 1: Creating alert")
        alert_id, ticket_id = alert_creator._create_alert()
    except Exception as e:
        logger.exception("[Device Monitor] Alert creation failed: %s", e)
        return jsonify({
            "success": False,
            "alert_created": False,
            "email_sent": False,
            "message": f"Alert creation failed: {e}",
        }), 500

    if alert_id is None:
        logger.error("[Device Monitor] Alert creation failed: alert_id=None ticket_id=%s", ticket_id)
        return jsonify({
            "success": False,
            "alert_created": False,
            "email_sent": False,
            "ticket_id": ticket_id,
            "message": "Alert creation failed",
        }), 500

    logger.info("[Device Monitor] Alert created successfully: alert_id=%s ticket_id=%s", alert_id, ticket_id)

    # Step 2: Run classification + unlock in background thread
    def process_alert_async():
        """Run classification and device unlock in background after response is sent."""
        try:
            logger.info("[Device Monitor] [Background] Starting classification for alertId=%s", alert_id)
            classified = alert_creator._classify_alert(alert_id)

            if classified:
                logger.info("[Device Monitor] [Background] Classification completed, starting unlock for alertId=%s", alert_id)
                unlocked = alert_creator._unlock_device(alert_id)
                if unlocked:
                    logger.info("[Device Monitor] [Background] ✅ Full alert flow completed for alertId=%s", alert_id)
                else:
                    logger.error("[Device Monitor] [Background] Unlock failed for alertId=%s", alert_id)
            else:
                logger.error("[Device Monitor] [Background] Classification failed for alertId=%s", alert_id)
        except Exception as e:
            logger.exception("[Device Monitor] [Background] Alert processing error: %s", e)

    threading.Thread(target=process_alert_async, daemon=True).start()
    logger.info("[Device Monitor] Classification and unlock queued in background for alertId=%s", alert_id)

    # Step 3: Send email notification in background thread
    def send_email_async():
        """Send email notification in background to avoid blocking response."""
        try:
            if device_config.is_email_configured:
                logger.info("[Device Monitor] [Background] Sending email notification")
                email_subject = f"Device Alert: Unlock Device IMEI{imei}"
                email_body = _build_email_body(alert_id, ticket_id, imei)
                email_result = emailer.send(subject=email_subject, lines=email_body)
                if email_result:
                    logger.info("[Device Monitor] [Background] ✅ Email sent successfully")
                else:
                    logger.warning("[Device Monitor] [Background] Email sending failed")
            else:
                logger.warning("[Device Monitor] [Background] Email not configured, skipping notification")
        except Exception as e:
            logger.exception("[Device Monitor] [Background] Email sending error: %s", e)

    threading.Thread(target=send_email_async, daemon=True).start()
    logger.info("[Device Monitor] Email notification queued in background")

    logger.info("[Device Monitor] ========== Request completed successfully ==========")

    return jsonify({
        "success": True,
        "alert_created": True,
        "email_sent": "queued",
        "alert_id": alert_id,
        "ticket_id": ticket_id,
        "imei": imei,
        "severity": "medium",
        "source": "Service Now",
        "alert_message": alert_message,
        "processing_status": "classification_and_unlock_queued",
        "processing_summary": "Alert created, classification and device unlock processing in background",
    }), 200


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "device_monitor",
        "imei_configured": bool(device_config.device_imei),
        "email_configured": device_config.is_email_configured,
        "alert_api_url": device_config.alert_api_url,
        "task_agent_unlock_url": device_config.task_agent_unlock_url,
    }), 200


def _build_email_body(alert_id, ticket_id, imei) -> list[str]:
    """Build email body for device unlock alert."""
    lines = [
        "Device Monitor Alert",
        "",
        f"Ticket ID: {ticket_id}",
        f"Alert ID: {alert_id}",
        f"Severity: medium",
        f"Source: Service Now",
        "",
        "--- Device Details ---",
        f"IMEI: {imei}",
        f"Action: Unlock the Device",
        f"Alert Message: Alert : Unlock the Device: IMEI{imei}",
        "",
        "--- Flow Status ---",
        f"Alert Created: ✅ (id={alert_id})",
        f"Classification: queued in background",
        f"Unlock Agent: queued in background",
        "",
        "This is an automated notification from Device Monitor.",
        "Classification and unlock steps will be processed by the alert system.",
    ]
    return lines


def run_server():
    """Start Flask server."""
    logger.info(
        "[Device Monitor] Starting API server on %s:%s",
        device_config.flask_host,
        device_config.flask_port,
    )
    app.run(
        host=device_config.flask_host,
        port=device_config.flask_port,
        debug=device_config.flask_debug,
        use_reloader=False,
    )
