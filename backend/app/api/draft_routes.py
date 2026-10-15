from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..deps import get_db
from ..models import Draft, DraftStatus, User
from ..schemas import DraftOut, DraftPatch
from ..services import drafts as svc

router = APIRouter(prefix="/drafts", tags=["drafts"], dependencies=[Depends(get_current_user)])


def draft_out(d: Draft) -> DraftOut:
    out = DraftOut.model_validate(d)
    out.email_subject = d.email.subject
    out.email_sender = d.email.sender
    return out


def _guard(fn, *args) -> DraftOut:
    try:
        return draft_out(fn(*args))
    except svc.DraftNotFound:
        raise HTTPException(404, "Draft not found") from None
    except svc.InvalidTransition as e:
        raise HTTPException(409, str(e)) from None


@router.get("", response_model=list[DraftOut])
def list_drafts(status: DraftStatus | None = None, db: Session = Depends(get_db)) -> list[DraftOut]:
    return [draft_out(d) for d in svc.list_drafts(db, status)]


@router.get("/{draft_id}", response_model=DraftOut)
def get_draft(draft_id: int, db: Session = Depends(get_db)) -> DraftOut:
    return _guard(svc.get_draft, db, draft_id)


@router.post("/{draft_id}/approve", response_model=DraftOut)
def approve(draft_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> DraftOut:
    """Marks the draft approved by a human. This does NOT send anything: there is no send path."""
    return _guard(svc.approve, db, draft_id, user.id)


@router.post("/{draft_id}/reject", response_model=DraftOut)
def reject(draft_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> DraftOut:
    return _guard(svc.reject, db, draft_id, user.id)


@router.patch("/{draft_id}", response_model=DraftOut)
def edit(draft_id: int, body: DraftPatch, db: Session = Depends(get_db)) -> DraftOut:
    """Edit the text of a still-pending draft. Edits never auto-approve."""
    return _guard(svc.edit, db, draft_id, body.edited_body)
