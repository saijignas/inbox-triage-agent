from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..agent import AgentConfig
from ..auth import get_current_user, require_admin
from ..deps import get_db
from ..models import Email, TriageStatus, User
from ..schemas import EmailCreate, EmailDetail, EmailSummary, SeedOut, TriageStarted
from ..services.emails import create_email, seed_sample_inbox
from ..services.triage import claim_triage, run_triage_job
from .draft_routes import draft_out

router = APIRouter(prefix="/emails", tags=["emails"], dependencies=[Depends(get_current_user)])


def _summary(e: Email) -> EmailSummary:
    return EmailSummary(
        id=e.id, sender=e.sender, subject=e.subject, received_at=e.received_at,
        triage_status=e.triage.status if e.triage else None,
        category=e.triage.category if e.triage else None,
        urgency=e.triage.urgency if e.triage else None,
        draft_status=e.draft.status if e.draft else None,
    )


def _load(db: Session, email_id: int) -> Email:
    email = db.scalar(
        select(Email)
        .options(joinedload(Email.triage), joinedload(Email.draft), joinedload(Email.tasks))
        .where(Email.id == email_id)
    )
    if email is None:
        raise HTTPException(404, "Email not found")
    return email


@router.post("", response_model=EmailSummary, status_code=201)
def add_email(body: EmailCreate, db: Session = Depends(get_db)) -> EmailSummary:
    try:
        return _summary(create_email(db, body))
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An email with this message_id already exists") from None


@router.post("/seed", response_model=SeedOut, status_code=201)
def seed(db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> SeedOut:
    added, total = seed_sample_inbox(db)
    return SeedOut(added=added, total=total)


@router.get("", response_model=list[EmailSummary])
def list_emails(
    db: Session = Depends(get_db), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)
) -> list[EmailSummary]:
    rows = db.scalars(
        select(Email)
        .options(joinedload(Email.triage), joinedload(Email.draft))
        .order_by(Email.received_at.desc(), Email.id.desc())
        .limit(limit).offset(offset)
    ).unique()
    return [_summary(e) for e in rows]


@router.get("/{email_id}", response_model=EmailDetail)
def get_email(email_id: int, db: Session = Depends(get_db)) -> EmailDetail:
    e = _load(db, email_id)
    return EmailDetail(
        id=e.id, sender=e.sender, subject=e.subject, body=e.body, received_at=e.received_at,
        triage=e.triage, tasks=e.tasks, draft=draft_out(e.draft) if e.draft else None,
    )


@router.post("/{email_id}/triage", response_model=TriageStarted, status_code=202)
def triage(
    email_id: int, request: Request, response: Response, background: BackgroundTasks, db: Session = Depends(get_db)
) -> TriageStarted:
    """Idempotent. Starts a background run unless one is queued/running/finished already.

    Returns 202 when a run was started, 200 when this was a no-op. A failed run can be retried
    by calling this again.
    """
    if db.get(Email, email_id) is None:
        raise HTTPException(404, "Email not found")
    result, claimed = claim_triage(db, email_id)
    if claimed:
        s = request.app.state
        cfg = AgentConfig(max_steps=s.settings.agent_max_steps, timeout_s=float(s.settings.agent_timeout_seconds))
        background.add_task(run_triage_job, s.session_factory, s.provider_factory, email_id, cfg)
    else:
        response.status_code = 200
    return TriageStarted(email_id=email_id, status=result.status if not claimed else TriageStatus.queued, started=claimed)
