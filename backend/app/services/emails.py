"""Email creation, pasted-text parsing, past-email search and the seeded sample inbox."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Email
from ..schemas import EmailCreate

SAMPLE_INBOX = Path(__file__).resolve().parent.parent / "data" / "sample_inbox.json"
_HEADER_RE = re.compile(r"^([A-Za-z][A-Za-z-]*):[ \t]*(.*)$")


def parse_raw_text(raw: str) -> tuple[str, str, str]:
    """Pasted text -> (sender, subject, body). Understands optional From:/Subject: header lines."""
    lines = raw.strip("\n").splitlines()
    headers: dict[str, str] = {}
    i = 0
    while i < len(lines):
        m = _HEADER_RE.match(lines[i])
        if not m:
            break
        headers[m.group(1).lower()] = m.group(2).strip()
        i += 1
    if headers.keys() & {"from", "subject"}:
        body = "\n".join(lines[i:]).strip()
        subject = headers.get("subject") or "(no subject)"
        sender = headers.get("from") or "unknown@pasted.invalid"
        return sender, subject, body or "(empty body)"
    first = next((ln.strip() for ln in lines if ln.strip()), "(no subject)")
    return "unknown@pasted.invalid", first[:120], raw.strip()


def create_email(db: Session, data: EmailCreate) -> Email:
    if data.raw_text:
        sender, subject, body = parse_raw_text(data.raw_text)
    else:
        sender, subject, body = data.sender or "", data.subject or "", data.body or ""
    email = Email(
        message_id=data.message_id,
        sender=sender[:255],
        subject=subject[:500],
        body=body,
        received_at=data.received_at or datetime.now(timezone.utc),
    )
    db.add(email)
    db.commit()
    return email


def search_emails(db: Session, query: str, limit: int = 3, exclude_id: int | None = None) -> list[dict[str, Any]]:
    """Keyword search (any word of 3+ chars) over subject and body. Read-only."""
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) >= 3][:6]
    if not words:
        return []
    conds = []
    for w in words:
        conds += [Email.subject.icontains(w, autoescape=True), Email.body.icontains(w, autoescape=True)]
    stmt = select(Email).where(or_(*conds))
    if exclude_id is not None:
        stmt = stmt.where(Email.id != exclude_id)
    rows = db.scalars(stmt.order_by(Email.received_at.desc(), Email.id.desc()).limit(limit)).all()
    return [
        {"id": e.id, "sender": e.sender, "subject": e.subject, "snippet": e.body[:120].replace("\n", " ")}
        for e in rows
    ]


def seed_sample_inbox(db: Session) -> tuple[int, int]:
    """Insert the fictional sample inbox. Idempotent: matched by message_id."""
    items = json.loads(SAMPLE_INBOX.read_text(encoding="utf-8"))
    existing = set(db.scalars(select(Email.message_id).where(Email.message_id.is_not(None))))
    added = 0
    for it in items:
        if it["message_id"] in existing:
            continue
        db.add(Email(message_id=it["message_id"], sender=it["sender"], subject=it["subject"], body=it["body"]))
        added += 1
    db.commit()
    return added, len(items)
