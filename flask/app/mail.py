from flask_mail import Message
from threading import Thread
from app import app, mail
import base64
import logging
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


logger = logging.getLogger(__name__)


def send_async_email(app, msg):
    with app.app_context():
        mail.send(msg)


def _send_via_gmail_api(data):
    refresh_token = app.config.get("GMAIL_REFRESH_TOKEN", "")
    client_id = app.config.get("GOOGLE_CLIENT_ID", "")
    client_secret = app.config.get("GOOGLE_SECRET", "")
    sender_email = app.config.get("GMAIL_SENDER_EMAIL", "")
    token_uri = app.config.get("GMAIL_TOKEN_URI", "https://oauth2.googleapis.com/token")

    if not refresh_token or not client_id or not client_secret or not sender_email:
        raise RuntimeError("Missing Gmail API configuration. Check GMAIL_* and GOOGLE_* variables.")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=token_uri,
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )
    creds.refresh(Request())

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    mime_msg = MIMEText(data.get("text", "") or data.get("html", ""), "html", "utf-8")
    mime_msg["to"] = ", ".join(data["recipients"])
    mime_msg["from"] = sender_email
    mime_msg["subject"] = data["subject"]

    raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def _send_via_smtp(data):
    bcc = data.get("bcc", [])
    attachments = data.get("attachments", [])
    msg = Message(
        data["subject"],
        sender=(app.config["MAIL_FROM"], app.config["MAIL_USERNAME"]),
        recipients=data["recipients"],
        bcc=bcc,
    )
    msg.body = data.get("text", "")
    msg.html = data.get("html", "")
    for target_filename, attachment in attachments:
        with open(attachment, "rb") as fh:
            msg.attach(
                filename=target_filename,
                disposition="attachment",
                content_type="application/pdf",
                data=fh.read(),
            )
    thr = Thread(target=send_async_email, args=[app, msg])
    thr.start()


def send_email(**data):
    provider = app.config.get("MAIL_PROVIDER", "smtp").lower()
    try:
        if provider == "gmail_api":
            _send_via_gmail_api(data)
            return
        _send_via_smtp(data)
    except Exception:
        logger.exception("Email sending failed using provider: %s", provider)
        raise
