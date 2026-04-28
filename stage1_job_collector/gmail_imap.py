"""Gmail IMAP 연결 및 채용 알림 메일 수집."""
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
from typing import Generator
import os


def _decode_str(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def connect(address: str, app_password: str) -> imaplib.IMAP4_SSL:
    """Gmail IMAP SSL 연결 반환."""
    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    mail.login(address, app_password)
    return mail


def fetch_alert_emails(
    mail: imaplib.IMAP4_SSL,
    sender_address: str,
    days_back: int = 1,
) -> Generator[dict, None, None]:
    """
    특정 발신자(사람인/잡코리아 등)의 알림 메일을 최근 N일치 가져옴.

    Yields:
        dict with keys: uid, subject, body_text, date
    """
    mail.select("INBOX")

    since_date = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
    # RFC 3501 검색: 발신자 + 날짜
    status, data = mail.search(
        None,
        f'(FROM "{sender_address}" SINCE "{since_date}")',
    )
    if status != "OK" or not data[0]:
        return

    uid_list = data[0].split()
    for uid in uid_list:
        status, msg_data = mail.fetch(uid, "(RFC822)")
        if status != "OK":
            continue

        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        # 제목 디코딩
        subject_parts = decode_header(msg.get("Subject", ""))
        subject = "".join(
            part.decode(enc or "utf-8") if isinstance(part, bytes) else part
            for part, enc in subject_parts
        )

        # 본문 추출 (text/plain 우선, 없으면 text/html)
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/plain":
                    body = _decode_str(part.get_payload(decode=True))
                    break
                if ct == "text/html" and not body:
                    body = _decode_str(part.get_payload(decode=True))
        else:
            body = _decode_str(msg.get_payload(decode=True))

        yield {
            "uid": uid.decode(),
            "subject": subject,
            "body_text": body,
            "date": msg.get("Date", ""),
        }
