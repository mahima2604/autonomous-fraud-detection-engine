"""SMTP email delivery for server-generated checkout verification codes."""
from email.message import EmailMessage
import os
import smtplib
import ssl


class DeliveryError(Exception):
    pass


def _settings():
    host = os.getenv("SMTP_HOST", "").strip()
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    sender = os.getenv("SMTP_FROM_EMAIL", "").strip()
    if not (host and username and password and sender):
        raise DeliveryError("Email OTP is not configured. Set the backend SMTP settings and try again.")
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError as error:
        raise DeliveryError("SMTP_PORT must be a valid port number.") from error
    if not 1 <= port <= 65535:
        raise DeliveryError("SMTP_PORT must be a valid port number.")
    return host, port, username, password, sender


def send_code(email_address, code):
    host, port, username, password, sender = _settings()
    message = EmailMessage()
    message["Subject"] = "Your checkout verification code"
    message["From"] = sender
    message["To"] = email_address
    message.set_content(
        f"Your checkout verification code is {code}. It expires in 10 minutes. "
        "If you did not request this code, you can ignore this email."
    )
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=12) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(username, password)
            refused = server.send_message(message)
            if refused:
                raise DeliveryError("The SMTP server did not accept the verification email.")
    except DeliveryError:
        raise
    except (OSError, smtplib.SMTPException) as error:
        raise DeliveryError("Email delivery failed. Check SMTP settings and try again later.") from error
    return True
