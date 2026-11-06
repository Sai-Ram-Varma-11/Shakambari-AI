import email.mime.multipart
import email.mime.text
import logging
import smtplib
from typing import Optional

import httpx

from ..config import settings

log = logging.getLogger("shakambari.mailer")


def render_otp_html(code: str, title: str, subtitle: str, expiry_minutes: int = 10) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #FBF7EE; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1C2A1F;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #FBF7EE; padding: 32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 540px; background-color: #FFFFFF; border-radius: 20px; border: 1px solid #E4E0D2; padding: 36px 32px; box-shadow: 0 4px 16px rgba(20,83,45,0.06);">
          <tr>
            <td align="center" style="padding-bottom: 24px;">
              <div style="display: inline-block; background-color: #FBF7EE; border: 1px solid #E4E0D2; border-radius: 14px; padding: 10px 18px;">
                <span style="font-size: 20px; font-weight: 800; color: #14532D; letter-spacing: -0.5px;">Shakambari</span>
                <span style="display: inline-block; background-color: #14532D; color: #F59E0B; font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 5px; margin-left: 6px;">AI</span>
              </div>
              <div style="font-size: 11px; font-weight: 600; color: #5B6B5E; letter-spacing: 1px; margin-top: 6px;">THINK SMART · SERVE RIGHT · WASTE LESS</div>
            </td>
          </tr>
          <tr>
            <td>
              <h1 style="font-size: 22px; font-weight: 700; color: #14532D; margin: 0 0 8px 0; text-align: center;">{title}</h1>
              <p style="font-size: 14px; color: #5B6B5E; margin: 0 0 24px 0; text-align: center;">{subtitle}</p>

              <div style="background-color: #ECF3E8; border: 2px dashed #14532D; border-radius: 14px; padding: 20px; text-align: center; margin: 24px 0;">
                <div style="font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1.5px; color: #5B6B5E; margin-bottom: 6px;">Verification Code</div>
                <div style="font-size: 38px; font-weight: 800; letter-spacing: 8px; color: #14532D; font-family: monospace;">{code}</div>
                <div style="font-size: 12px; color: #C2410C; margin-top: 8px; font-weight: 500;">Valid for {expiry_minutes} minutes · Single use</div>
              </div>

              <p style="font-size: 13px; color: #5B6B5E; line-height: 1.6; margin: 24px 0 0 0;">
                If you did not request this code, you can safely ignore this email. Someone may have mistyped their email address.
              </p>
            </td>
          </tr>
          <tr>
            <td style="border-top: 1px solid #E4E0D2; padding-top: 20px; margin-top: 28px; text-align: center;">
              <p style="font-size: 11px; color: #5B6B5E; margin: 0;">
                Shakambari AI · Campus Food Waste Intelligence & Verified Surplus Redistribution<br>
                Strictly Lacto-Vegetarian Food Policy
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def render_general_html(title: str, message: str, action_url: Optional[str] = None, action_text: Optional[str] = None) -> str:
    action_html = ""
    if action_url and action_text:
        action_html = f"""
        <div style="text-align: center; margin: 24px 0;">
          <a href="{action_url}" style="background-color: #14532D; color: #FFFFFF; font-weight: 600; font-size: 14px; text-decoration: none; padding: 12px 24px; border-radius: 10px; display: inline-block;">
            {action_text}
          </a>
        </div>
        """
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{title}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #FBF7EE; font-family: sans-serif; color: #1C2A1F;">
  <div style="padding: 32px 16px; text-align: center;">
    <div style="max-width: 520px; margin: 0 auto; background: #FFF; border: 1px solid #E4E0D2; border-radius: 18px; padding: 32px; text-align: left;">
      <h2 style="color: #14532D; margin-top: 0;">{title}</h2>
      <p style="color: #1C2A1F; font-size: 15px; line-height: 1.6;">{message}</p>
      {action_html}
      <hr style="border: none; border-top: 1px solid #E4E0D2; margin: 24px 0;">
      <p style="font-size: 11px; color: #5B6B5E;">Shakambari AI · Strictly Lacto-Vegetarian Food Ecosystem</p>
    </div>
  </div>
</body>
</html>"""


def send_email(to: str, subject: str, html: str, text: str) -> bool:
    """Dispatches email via configured provider (smtp, resend, or brevo).
    Logs error gracefully and never raises exception to crash request."""
    provider = (settings.email_provider or "smtp").lower().strip()

    try:
        if provider == "resend":
            return _send_via_resend(to, subject, html, text)
        elif provider == "brevo":
            return _send_via_brevo(to, subject, html, text)
        else:
            return _send_via_smtp(to, subject, html, text)
    except Exception as exc:
        log.error("Failed to deliver email to %s (subject: '%s'): %s", to, subject, exc)
        return False


def _send_via_smtp(to: str, subject: str, html: str, text: str) -> bool:
    if not settings.smtp_user or not settings.smtp_password:
        log.info("SMTP credentials not configured. Email to %s skipped (Subject: %s).", to, subject)
        return True

    msg = email.mime.multipart.MIMEMultipart("alternative")
    msg["Subject"] = subject
    from_name = settings.mail_from_name or "Shakambari AI"
    from_addr = settings.mail_from_address or settings.smtp_user
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = to

    msg.attach(email.mime.text.MIMEText(text, "plain", "utf-8"))
    msg.attach(email.mime.text.MIMEText(html, "html", "utf-8"))

    host = settings.smtp_host or "smtp.gmail.com"
    port = int(settings.smtp_port or 587)

    with smtplib.SMTP(host, port, timeout=12) as s:
        s.ehlo()
        if port != 465:
            s.starttls()
            s.ehlo()
        s.login(settings.smtp_user, settings.smtp_password)
        s.sendmail(from_addr, [to], msg.as_string())
        log.info("Email delivered via SMTP to %s (Subject: %s)", to, subject)
        return True


def _send_via_resend(to: str, subject: str, html: str, text: str) -> bool:
    api_key = settings.resend_api_key
    if not api_key:
        log.warning("Resend API key not configured; skipping email to %s", to)
        return True
    from_addr = settings.mail_from_address or "noreply@shakambari.demo"
    from_name = settings.mail_from_name or "Shakambari AI"
    res = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from": f"{from_name} <{from_addr}>",
            "to": [to],
            "subject": subject,
            "html": html,
            "text": text,
        },
        timeout=10.0,
    )
    if res.is_success:
        log.info("Email delivered via Resend to %s", to)
        return True
    else:
        log.error("Resend delivery failed (%s): %s", res.status_code, res.text)
        return False


def _send_via_brevo(to: str, subject: str, html: str, text: str) -> bool:
    api_key = settings.brevo_api_key
    if not api_key:
        log.warning("Brevo API key not configured; skipping email to %s", to)
        return True
    from_addr = settings.mail_from_address or "noreply@shakambari.demo"
    from_name = settings.mail_from_name or "Shakambari AI"
    res = httpx.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": api_key, "Content-Type": "application/json"},
        json={
            "sender": {"name": from_name, "email": from_addr},
            "to": [{"email": to}],
            "subject": subject,
            "htmlContent": html,
            "textContent": text,
        },
        timeout=10.0,
    )
    if res.is_success:
        log.info("Email delivered via Brevo to %s", to)
        return True
    else:
        log.error("Brevo delivery failed (%s): %s", res.status_code, res.text)
        return False
