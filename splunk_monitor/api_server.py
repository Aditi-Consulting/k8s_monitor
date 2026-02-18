"""Flask API server with /fetch-users endpoint."""
from __future__ import annotations

import logging
import threading
from flask import Flask, jsonify

from .config import splunk_config
from .api_client import external_api_client, ApplicationException
from .llm_analyzer import llm_analyzer
from .alert_creator import alert_creator
from k8s_monitor.emailer import emailer

logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/fetch-users', methods=['GET', 'POST'])
def trigger_exception():
    """
    Endpoint to trigger external API call and process exception.

    Workflow:
    1. Call external Spring Boot API
    2. If exception detected, analyze with LLM
    3. Create alert (create -> classify -> solve flow)
    4. Send email notification

    Returns JSON response with details.
    """
    logger.info("[Splunk Monitor] ========== Received fetch-users request ==========")

    # Step 1: Call external Spring Boot API
    try:
        logger.info("[Splunk Monitor] Step 1: Calling external Spring Boot API")
        exception = external_api_client.call_external_api()
    except Exception as e:
        logger.exception("[Splunk Monitor] Failed to call external API: %s", e)
        return jsonify({
            "success": False,
            "exception_detected": False,
            "alert_created": False,
            "email_sent": False,
            "processing_summary": f"Failed to call external API: {str(e)}"
        }), 500

    if exception is None:
        logger.info("[Splunk Monitor] [API Client] API call successful (no exception)")
        return jsonify({
            "success": True,
            "exception_detected": False,
            "alert_created": False,
            "email_sent": False,
            "processing_summary": "External API call completed successfully (no exception)"
        }), 200

    logger.warning("[Splunk Monitor] Exception detected: type=%s status=%s message=%s",
                   exception.error, exception.status, exception.message[:100])

    # Step 2: Analyze exception with LLM
    try:
        logger.info("[Splunk Monitor] Step 2: Analyzing exception with LLM")
        llm_analysis = llm_analyzer.analyze_exception(exception)

        # Log which analysis method was used
        analysis_source = llm_analysis.get('analysis_source', 'UNKNOWN')
        if analysis_source == 'LLM':
            logger.info("[Splunk Monitor] ✅ LLM analysis completed: severity=%s alert_message=%s",
                       llm_analysis.get('severity'), (llm_analysis.get('alert_message') or '')[:80])
        else:
            logger.warning("[Splunk Monitor] 🔧 Fallback analysis used: severity=%s alert_message=%s",
                          llm_analysis.get('severity'), (llm_analysis.get('alert_message') or '')[:80])
    except Exception as e:
        logger.exception("[Splunk Monitor] LLM analysis failed: %s", e)
        return jsonify({
            "success": False,
            "exception_detected": True,
            "alert_created": False,
            "email_sent": False,
            "exception_details": exception.to_dict(),
            "processing_summary": f"LLM analysis failed: {str(e)}"
        }), 500

    # Step 3: Create alert (Stage 1 only - return immediately)
    try:
        logger.info("[Splunk Monitor] Step 3: Creating alert")
        alert_id, ticket_id = alert_creator._create_alert(exception, llm_analysis)
    except Exception as e:
        logger.exception("[Splunk Monitor] Alert creation failed: %s", e)
        return jsonify({
            "success": False,
            "exception_detected": True,
            "alert_created": False,
            "email_sent": False,
            "exception_details": exception.to_dict(),
            "processing_summary": f"Alert creation failed: {str(e)}"
        }), 500

    if alert_id is None:
        logger.error("[Splunk Monitor] Alert creation failed: alert_id=None ticket_id=%s", ticket_id)
        return jsonify({
            "success": False,
            "exception_detected": True,
            "alert_created": False,
            "email_sent": False,
            "ticket_id": ticket_id,
            "alert_message": llm_analysis.get("alert_message", ""),
            "severity": llm_analysis.get("severity", "medium"),
            "exception_details": exception.to_dict(),
            "processing_summary": "Alert creation/processing failed"
        }), 500

    logger.info("[Splunk Monitor] Alert created successfully: alert_id=%s ticket_id=%s", alert_id, ticket_id)

    # Step 4: Run classification + task agent in background thread
    def process_alert_async():
        """Run classification and remediation in background after response is sent."""
        try:
            logger.info("[Splunk Monitor] [Background] Starting classification for alertId=%s", alert_id)
            classified = alert_creator._classify_alert(alert_id)

            if classified:
                logger.info("[Splunk Monitor] [Background] Classification completed, starting task agent for alertId=%s", alert_id)
                solved = alert_creator._solve_alert(alert_id)
                if solved:
                    logger.info("[Splunk Monitor] [Background] ✅ Full alert flow completed for alertId=%s", alert_id)
                else:
                    logger.error("[Splunk Monitor] [Background] Task agent failed for alertId=%s", alert_id)
            else:
                logger.error("[Splunk Monitor] [Background] Classification failed for alertId=%s", alert_id)
        except Exception as e:
            logger.exception("[Splunk Monitor] [Background] Alert processing error: %s", e)

    threading.Thread(target=process_alert_async, daemon=True).start()
    logger.info("[Splunk Monitor] Classification and remediation queued in background for alertId=%s", alert_id)

    # Step 5: Send email notification in background thread
    def send_email_async():
        """Send email notification in background to avoid blocking response."""
        try:
            if splunk_config.is_email_configured:
                logger.info("[Splunk Monitor] [Background] Sending email notification")
                email_subject = f"Splunk Alert: {ticket_id}"
                email_body = _build_email_body(exception, llm_analysis, ticket_id)
                email_result = emailer.send(subject=email_subject, lines=email_body)
                if email_result:
                    logger.info("[Splunk Monitor] [Background] Email sent successfully to %s",
                               splunk_config.email_receiver)
                else:
                    logger.warning("[Splunk Monitor] [Background] Email sending failed")
            else:
                logger.warning("[Splunk Monitor] [Background] Email not configured, skipping notification")
        except Exception as e:
            logger.exception("[Splunk Monitor] [Background] Email sending error: %s", e)

    # Start email sending in background thread
    threading.Thread(target=send_email_async, daemon=True).start()
    logger.info("[Splunk Monitor] Email notification queued in background")

    logger.info("[Splunk Monitor] ========== Request completed successfully ==========")

    return jsonify({
        "success": True,
        "exception_detected": True,
        "alert_created": True,
        "email_sent": "queued",
        "alert_id": alert_id,
        "ticket_id": ticket_id,
        "alert_message": llm_analysis.get("alert_message", ""),
        "severity": llm_analysis.get("severity", "medium"),
        "analysis_source": llm_analysis.get("analysis_source", "UNKNOWN"),
        "model": llm_analysis.get("model"),
        "fallback_reason": llm_analysis.get("fallback_reason"),
        "llm_attempts": llm_analysis.get("llm_attempts", 0),
        "exception_details": exception.to_dict(),
        "processing_status": "classification_and_remediation_queued",
        "processing_summary": "Alert created successfully, classification and remediation processing in background"
    }), 200

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "splunk_monitor",
        "openai_configured": splunk_config.is_openai_configured,
        "email_configured": splunk_config.is_email_configured,
        "external_app_url": splunk_config.external_app_url,
        "alert_api_url": splunk_config.alert_api_url
    }), 200

def _build_email_body(exception: ApplicationException, llm_analysis, ticket_id) -> list[str]:
    """Build email body with analysis transparency."""
    analysis_source = llm_analysis.get('analysis_source', 'UNKNOWN')
    model = llm_analysis.get('model')
    fallback_reason = llm_analysis.get('fallback_reason')

    # Build analysis source description
    if analysis_source == 'LLM' and model:
        analysis_info = f"✅ AI-Generated Alert (Model: {model})"
    elif analysis_source == 'FALLBACK' and fallback_reason:
        analysis_info = f"🔧 Deterministic Fallback (Reason: {fallback_reason})"
    else:
        analysis_info = "⚠️ Unknown Analysis Method"

    lines = [
        "**Splunk Monitor Alert**",
        "",
        f"**Ticket ID:** {ticket_id}",
        f"**Severity:** {llm_analysis.get('severity', 'medium')}",
        f"**Analysis Method:** {analysis_info}",
        "",
        "**Issue Description:**",
        llm_analysis.get('alert_message', 'Alert: No analysis available'),
        "",
        "─" * 60,
        "**Technical Evidence:**",
        "",
        f"• Endpoint: {exception.path}",
        f"• Status Code: {exception.status}",
        f"• Error Type: {exception.error}",
        f"• Error Code: {exception.code or 'N/A'}",
        f"• Error Message: {exception.message}",
        f"• Location: {exception.location or 'Unknown'}",
        f"• Timestamp: {exception.timestamp}",
        f"• Environment: production",
        f"• Source: splunk_monitor",
        "",
        "─" * 60,
        "**Monitoring System:**",
        f"• Service: Splunk Monitor",
        f"• Alert API: {splunk_config.alert_api_url}",
        f"• External App: {splunk_config.external_app_url}{splunk_config.external_app_endpoint}",
        "",
        "**Note:** This alert follows the 3-layer architecture:",
        "1. Alert Signal: Clean operational issue description (above)",
        "2. Evidence: Structured technical facts (above)",
        "3. Classification/Remediation: Handled by downstream agents",
        "",
        "_This is an automated notification from Splunk Monitor._",
        "_Classification and remediation steps will be processed by the alert system._"
    ]

    return lines

def run_server():
    """Start Flask server."""
    logger.info(
        "[Splunk Monitor] Starting API server on %s:%s",
        splunk_config.flask_host,
        splunk_config.flask_port
    )
    app.run(
        host=splunk_config.flask_host,
        port=splunk_config.flask_port,
        debug=splunk_config.flask_debug
    )
