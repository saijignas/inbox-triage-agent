"""Draft state machine.

    pending --approve--> approved
    pending --reject---> rejected
    pending --edit-----> pending (edited_body set)

approved / rejected are terminal. Every transition is a compare-and-set UPDATE guarded by
`status == pending`, so double-clicks and races cannot flip a decided draft.

IMPORTANT: 'approved' only records that a human accepted the text. Nothing in this codebase
sends email; there is no transport and no 'sent' status.
"""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload

from ..models import Draft, DraftStatus, utcnow


class DraftNotFound(Exception):
    pass


class InvalidTransition(Exception):
    pass


def get_draft(db: Session, draft_id: int) -> Draft:
    draft = db.scalar(select(Draft).options(joinedload(Draft.email)).where(Draft.id == draft_id))
    if draft is None:
        raise DraftNotFound(draft_id)
    return draft


def _guarded_update(db: Session, draft_id: int, **values) -> Draft:
    get_draft(db, draft_id)  # 404 if missing
    res = db.execute(
        update(Draft).where(Draft.id == draft_id, Draft.status == DraftStatus.pending).values(**values)
    )
    db.commit()
    if res.rowcount != 1:
        current = get_draft(db, draft_id)
        raise InvalidTransition(f"draft is already {current.status.value}")
    db.expire_all()
    return get_draft(db, draft_id)


def approve(db: Session, draft_id: int, user_id: int) -> Draft:
    return _guarded_update(db, draft_id, status=DraftStatus.approved, decided_at=utcnow(), decided_by=user_id)


def reject(db: Session, draft_id: int, user_id: int) -> Draft:
    return _guarded_update(db, draft_id, status=DraftStatus.rejected, decided_at=utcnow(), decided_by=user_id)


def edit(db: Session, draft_id: int, edited_body: str) -> Draft:
    return _guarded_update(db, draft_id, edited_body=edited_body)


def list_drafts(db: Session, status: DraftStatus | None) -> list[Draft]:
    stmt = select(Draft).options(joinedload(Draft.email)).order_by(Draft.created_at.desc(), Draft.id.desc())
    if status is not None:
        stmt = stmt.where(Draft.status == status)
    return list(db.scalars(stmt))
