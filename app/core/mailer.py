import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from urllib.parse import quote

from app.core.config import settings

logger = logging.getLogger(__name__)


def build_link(path: str, token: str, **extra: str) -> str:
    """Frontend URL with a URL-encoded token (and optional extra query params)."""
    query = f"token={quote(token, safe='')}"
    for key, value in extra.items():
        query += f"&{key}={quote(value, safe='')}"
    return f"{settings.FRONTEND_URL.rstrip('/')}{path}?{query}"


def send_mail(to: str, subject: str, plain: str, html: str | None = None) -> bool:
    """Send an e-mail. Returns False (and logs) on failure — never raises."""
    if html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(plain, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
    else:
        msg = MIMEText(plain, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_USER
    msg["To"] = to

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception:
        logger.exception("Не вдалося надіслати лист на %s (%s)", to, subject)
        return False


def send_action_mail(
    to: str,
    subject: str,
    intro: str,
    button_label: str,
    link: str,
    valid_for: str,
) -> bool:
    """Standard 'press the button' e-mail (plain + HTML) used for all one-time links."""
    # the plain-text part has no button
    plain_intro = intro.replace("натисніть кнопку нижче", "скористайтеся посиланням нижче")
    plain = (
        f"Доброго дня!\n\n{plain_intro}\n\n"
        f"{link}\n\n"
        f"Посилання дійсне {valid_for}."
    )
    html = f"""\
<!DOCTYPE html>
<html lang="uk">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;background:#f4f4f4;margin:0;padding:0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:40px 0;">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0"
             style="max-width:560px;background:#ffffff;border-radius:12px;padding:40px;">
        <tr><td style="padding-bottom:24px;">
          <h2 style="margin:0;color:#1a1a1a;font-size:22px;">ЗЗК Реєстр</h2>
        </td></tr>
        <tr><td style="color:#444;font-size:15px;line-height:1.6;padding-bottom:28px;">
          <p style="margin:0 0 12px 0;">Доброго дня!</p>
          <p style="margin:0;">{escape(intro)}</p>
        </td></tr>
        <tr><td align="center" style="padding-bottom:28px;">
          <a href="{escape(link)}"
             style="display:inline-block;background:#4F46E5;color:#ffffff;text-decoration:none;
                    font-size:15px;font-weight:600;padding:14px 32px;border-radius:8px;">
            {escape(button_label)}
          </a>
        </td></tr>
        <tr><td style="color:#888;font-size:13px;line-height:1.5;border-top:1px solid #eee;padding-top:20px;">
          <p style="margin:0 0 8px 0;">Якщо кнопка не працює, скопіюйте це посилання у браузер:</p>
          <p style="margin:0;word-break:break-all;color:#4F46E5;">{escape(link)}</p>
          <p style="margin:12px 0 0 0;">Посилання дійсне {escape(valid_for)}.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
    return send_mail(to, subject, plain, html)
