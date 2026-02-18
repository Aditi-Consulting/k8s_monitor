"""Simple SMTP email sender with TLS."""
from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Iterable
from .config import config

logger = logging.getLogger(__name__)

class Emailer:
    def __init__(self):
        if not config.is_email_configured:
            logger.warning("Email configuration incomplete; emails will not be sent.")

    def send(self, subject: str, lines: Iterable[str]):
        if not config.is_email_configured:
            return False
        body = "\n".join(lines)
        if len(body) > config.max_email_body_length:
            body = body[: config.max_email_body_length] + "\n... (truncated)"

        # Parse multiple receivers (comma-separated)
        receivers = [r.strip() for r in config.email_receiver.split(',') if r.strip()]

        msg = MIMEMultipart()
        msg['From'] = config.email_sender
        msg['To'] = ', '.join(receivers)  # Format for email header
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        try:
            with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as smtp:
                smtp.starttls()
                smtp.login(config.email_user, config.email_pass)
                smtp.sendmail(config.email_sender, receivers, msg.as_string())  # Pass list of receivers
            logger.info("Sent email to %d recipient(s): %s", len(receivers), subject)
            return True
        except Exception as e:
            logger.error("Failed sending email: %s", e)
            return False

emailer = Emailer()

