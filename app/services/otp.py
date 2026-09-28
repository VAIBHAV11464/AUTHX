import smtplib
from email.message import EmailMessage

from flask import current_app


def deliver_otp(username, code):
    user = current_app.config.get("SMTP_USER") or ""
    password = current_app.config.get("SMTP_PASSWORD") or ""
    if user and password:
        try:
            _send_mail(username, code)
            return "email"
        except Exception as exc:
            print(f"AuthX OTP email failed ({exc}); printing code instead.", flush=True)
    print(f"AuthX OTP for {username}: {code}", flush=True)
    return "console"


def _send_mail(username, code):
    cfg = current_app.config
    to_addr = cfg["SMTP_USER"]
    msg = EmailMessage()
    msg["Subject"] = "AuthX login code"
    msg["From"] = cfg["SMTP_USER"]
    msg["To"] = to_addr
    msg.set_content(f"Login code for {username}: {code}\nValid for {cfg['OTP_MINUTES']} minutes.")
    with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=10) as smtp:
        smtp.starttls()
        smtp.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
        smtp.send_message(msg)
