"""Notification dispatchers — alert on run failure or success.

Supported channels
------------------
- ``email``   — SMTP (with STARTTLS)
- ``slack``   — Incoming Webhook POST
- ``webhook`` — Generic HTTP POST (JSON body)
- ``teams``   — Microsoft Teams Incoming Webhook

Configuration (``loader.yaml``)::

    notifications:
      on_failure:
        - kind: email
          smtp_host: smtp.gmail.com
          smtp_port: 587
          from_addr: eds@company.com
          to: [data-team@company.com]
          password_env: SMTP_PASSWORD
        - kind: slack
          webhook_url_env: SLACK_WEBHOOK_URL
      on_success:
        - kind: webhook
          url: https://monitoring.company.com/api/runs
          method: POST

Design principles
-----------------
- Notification failures are **never fatal** — a failed Slack call must not
  crash the loader.  All dispatchers catch exceptions and log them.
- Credentials are read from environment variables (``_env`` suffix fields).
- The :func:`dispatch_notifications` function is the single entry point;
  the loader calls it once after every run.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import urllib.error
import urllib.request
from email.mime.text import MIMEText
from typing import Any

logger = logging.getLogger("eds_loader._notifications")

__all__ = ["dispatch_notifications"]


# ---------------------------------------------------------------------------
# Individual dispatchers
# ---------------------------------------------------------------------------

def _send_email(cfg: dict[str, Any], subject: str, body: str) -> None:
    """Send an SMTP notification.

    Required config keys: ``smtp_host``, ``from_addr``, ``to`` (list[str]).
    Optional: ``smtp_port`` (default 587), ``password`` or ``password_env``.
    """
    host: str = cfg.get("smtp_host", "")
    port: int = int(cfg.get("smtp_port", 587))
    from_addr: str = cfg.get("from_addr", "eds-loader@localhost")
    to_addrs: list[str] = cfg.get("to", [])
    if not host or not to_addrs:
        logger.warning("email notification: smtp_host and to are required — skipped")
        return

    password: str | None = cfg.get("password")
    if not password:
        env_key = cfg.get("password_env", "")
        if env_key:
            password = os.environ.get(env_key)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)

    try:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            if password:
                smtp.login(from_addr, password)
            smtp.sendmail(from_addr, to_addrs, msg.as_string())
        logger.info("Email notification sent to %s", to_addrs)
    except Exception as exc:
        logger.warning("Email notification failed: %s", exc)


def _send_slack(cfg: dict[str, Any], subject: str, body: str) -> None:
    """POST to a Slack Incoming Webhook.

    Required config keys: ``webhook_url`` or ``webhook_url_env``.
    """
    url: str = cfg.get("webhook_url", "")
    if not url:
        env_key = cfg.get("webhook_url_env", "")
        url = os.environ.get(env_key, "") if env_key else ""
    if not url:
        logger.warning("slack notification: webhook_url / webhook_url_env required — skipped")
        return

    payload = json.dumps({"text": f"*{subject}*\n{body}"}).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info("Slack notification sent (HTTP %s)", resp.status)
    except Exception as exc:
        logger.warning("Slack notification failed: %s", exc)


def _send_teams(cfg: dict[str, Any], subject: str, body: str) -> None:
    """POST to a Microsoft Teams Incoming Webhook.

    Required config keys: ``webhook_url`` or ``webhook_url_env``.
    """
    url: str = cfg.get("webhook_url", "")
    if not url:
        env_key = cfg.get("webhook_url_env", "")
        url = os.environ.get(env_key, "") if env_key else ""
    if not url:
        logger.warning("teams notification: webhook_url / webhook_url_env required — skipped")
        return

    payload = json.dumps({
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "summary": subject,
        "themeColor": "FF0000" if "FAIL" in subject.upper() else "00FF00",
        "title": subject,
        "text": body,
    }).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info("Teams notification sent (HTTP %s)", resp.status)
    except Exception as exc:
        logger.warning("Teams notification failed: %s", exc)


def _send_webhook(cfg: dict[str, Any], subject: str, body: str, payload: dict[str, Any]) -> None:
    """POST JSON to a generic HTTP endpoint.

    Required config keys: ``url``.
    Optional: ``method`` (default POST), ``headers`` (dict).
    """
    url: str = cfg.get("url", "")
    if not url:
        logger.warning("webhook notification: url required — skipped")
        return

    method: str = cfg.get("method", "POST").upper()
    extra_headers: dict[str, str] = cfg.get("headers", {})
    headers = {"Content-Type": "application/json", **extra_headers}
    data = json.dumps({**payload, "subject": subject, "body": body}).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info("Webhook notification sent (HTTP %s)", resp.status)
    except Exception as exc:
        logger.warning("Webhook notification failed: %s", exc)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def dispatch_notifications(
    notification_cfg: dict[str, list[dict[str, Any]]],
    run_status: str,   # "success" or "failed"
    subject: str,
    body: str,
    payload: dict[str, Any],
) -> None:
    """Send all applicable notifications for a completed run.

    Args:
        notification_cfg: Parsed ``notifications`` block from ``loader.yaml``.
            Keys: ``on_failure``, ``on_success``, ``always``.
        run_status: ``"success"`` or ``"failed"``.
        subject: Short subject / title for the notification.
        body: Human-readable summary text.
        payload: Full run metrics dict for webhook payloads.
    """
    if not notification_cfg:
        return

    channels: list[dict[str, Any]] = []
    channels.extend(notification_cfg.get("always", []))
    if run_status == "failed":
        channels.extend(notification_cfg.get("on_failure", []))
    if run_status == "success":
        channels.extend(notification_cfg.get("on_success", []))

    for ch in channels:
        kind = ch.get("kind", "").lower()
        try:
            if kind == "email":
                _send_email(ch, subject, body)
            elif kind == "slack":
                _send_slack(ch, subject, body)
            elif kind == "teams":
                _send_teams(ch, subject, body)
            elif kind == "webhook":
                _send_webhook(ch, subject, body, payload)
            else:
                logger.warning("Unknown notification kind %r — skipped", kind)
        except Exception as exc:
            # Safety net: never let notification failure crash the loader.
            logger.warning("Notification dispatch error (%s): %s", kind, exc)
