"""Discovery pipeline: fetch -> normalise -> dedupe/upsert -> analyse -> notify. No AI involved."""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import analysis
from .core import emit, get_setting, notify, set_setting
from .db import utcnow
from .models import Application, Company, Job, Profile
from .normalize import (
    canonical_url,
    extract_salary,
    fingerprint,
    is_relevant_title,
    parse_location,
    role_family,
    summarize_role,
)
from .schemas import ProfileData, seed_profile
from .sources import ADAPTERS, PoliteClient, RawJob, SourceError

log = logging.getLogger("sonic.discovery")

VISA_LABEL = {"confirmed": "Confirmed", "conditional": "Conditional", "unverified": "Unverified",
              "not_supported": "Not supported", "not_required": "Not needed"}


def load_profile(db: Session) -> ProfileData:
    row = db.get(Profile, 1)
    if row is None:
        data = seed_profile()
        db.add(Profile(id=1, data=data.model_dump()))
        db.flush()
        return data
    return ProfileData.model_validate(row.data or {})


def apply_analysis(job: Job, profile: ProfileData, *, description_html: str = "") -> None:
    """(Re)compute all deterministic analysis fields for a job. Manual overrides are preserved."""
    now = utcnow()
    visa = analysis.analyze_visa(
        job.description_text, country=job.country, remote_mode=job.remote_mode, remote_scope=job.remote_scope,
        location_raw=job.location_raw, source_url=job.canonical_url, profile=profile, now=now,
    )
    elig = analysis.analyze_eligibility(
        title=job.title, description=job.description_text, employment_type=job.employment_type, visa=visa,
        profile=profile, source_url=job.canonical_url, is_active=job.is_active,
    )
    fit = analysis.score_fit(
        title=job.title, description=job.description_text, role_family=job.role_family,
        level=elig["experience_level"], min_years=elig["min_years"], eligibility=elig["eligibility"], visa=visa,
        country=job.country, region=job.region, remote_mode=job.remote_mode,
        salary_min=job.salary_min, salary_currency=job.salary_currency, profile=profile,
    )
    job.visa_status = visa["visa_status"]
    job.visa_evidence = visa["visa_evidence"]
    job.visa_checked_at = now
    job.relocation = visa["relocation"]
    job.relocation_evidence = visa["relocation_evidence"]
    job.remote_from_morocco = visa["remote_from_morocco"]
    job.experience_level = elig["experience_level"]
    job.min_years = elig["min_years"]
    if not job.manual_override:
        job.eligibility = elig["eligibility"]
    job.eligibility_reasons = elig["eligibility_reasons"]
    job.fit_score = fit["fit_score"]
    job.fit_stars = fit["fit_stars"]
    job.fit_reason = fit["fit_reason"]
    job.fit_breakdown = fit["fit_breakdown"]
    job.analysis_source = "rules"


def _apply_raw(job: Job, raw: RawJob, provider: str) -> None:
    loc = parse_location(raw.location, raw.country_hint, raw.remote_hint, raw.workplace)
    job.title = raw.title[:300]
    job.canonical_url = canonical_url(raw.url)[:600]
    job.source_url = raw.url[:600]
    job.apply_url = (raw.apply_url or raw.url)[:600]
    job.location_raw = raw.location[:400]
    job.country = loc["country"]
    job.region = loc["region"]
    job.remote_mode = loc["remote_mode"]
    job.remote_scope = loc["remote_scope"]
    job.department = raw.department[:200]
    job.employment_type = raw.employment_type[:60]
    job.description_text = raw.description_text
    job.summary = summarize_role(raw.description_html, raw.description_text)
    sal = raw.salary or extract_salary(raw.description_text)
    job.salary_text = (sal.get("text") or "")[:200]
    job.salary_min = sal.get("min")
    job.salary_max = sal.get("max")
    job.salary_currency = (sal.get("currency") or "")[:8]
    job.posted_at = raw.posted_at
    job.role_family = role_family(raw.title)


def sync_company(db: Session, company: Company, client: PoliteClient, profile: ProfileData,
                 search_cfg: Optional[dict] = None) -> dict:
    """Fetch one company board and reconcile it with the database."""
    search_cfg = search_cfg or {}
    adapter = ADAPTERS.get(company.provider)
    stats = {"fetched": 0, "relevant": 0, "new": 0, "updated": 0, "closed": 0, "reopened": 0, "new_ids": []}
    if adapter is None:
        company.last_status = f"unknown provider {company.provider}"
        return stats
    now = utcnow()
    try:
        raws = adapter.fetch(client, company.board_token)
    except SourceError as e:
        company.fail_count += 1
        company.last_status = f"error: {e}"[:255]
        company.last_fetch_at = now
        return stats
    company.fail_count = 0
    company.last_fetch_at = now
    company.last_job_count = len(raws)
    stats["fetched"] = len(raws)

    existing = {j.external_id: j for j in db.scalars(select(Job).where(Job.company_id == company.id))}
    seen_ids: set[str] = set()
    for raw in raws:
        if not raw.external_id or not raw.title or not raw.url:
            continue
        seen_ids.add(raw.external_id)
        if not is_relevant_title(raw.title, search_cfg.get("extra_title_keywords"), search_cfg.get("exclude_title_keywords")):
            continue
        stats["relevant"] += 1
        fp = fingerprint(raw.title, raw.location, raw.description_text)
        job = existing.get(raw.external_id)
        if job is None:
            # secondary dedupe: same canonical URL already known under another id
            dup = db.scalar(select(Job).where(Job.canonical_url == canonical_url(raw.url), Job.company_id == company.id))
            if dup is not None:
                dup.last_seen_at = now
                continue
            job = Job(company_id=company.id, provider=company.provider, external_id=raw.external_id, fingerprint=fp,
                      discovered_at=now, last_seen_at=now, last_verified_at=now, is_active=True)
            _apply_raw(job, raw, company.provider)
            apply_analysis(job, profile)
            job.stage = "verified"  # just read from the official source
            db.add(job)
            db.flush()
            stats["new"] += 1
            stats["new_ids"].append(job.id)
        else:
            job.last_seen_at = now
            job.last_verified_at = now
            changed = job.fingerprint != fp
            reopened = not job.is_active
            if reopened:
                job.is_active = True
                job.closed_at = None
                stats["reopened"] += 1
            if changed:
                _apply_raw(job, raw, company.provider)
                job.fingerprint = fp
                job.updated_content_at = now
                job.seen = False
                stats["updated"] += 1
            if changed or reopened:
                apply_analysis(job, profile)

    # jobs that vanished from the official board are closed
    for ext_id, job in existing.items():
        if ext_id not in seen_ids and job.is_active:
            job.is_active = False
            job.closed_at = now
            job.last_verified_at = now
            if not job.manual_override:
                apply_analysis(job, profile)
            stats["closed"] += 1
            app = db.scalar(select(Application).where(Application.job_id == job.id))
            if app is not None and app.status not in ("submitted", "withdrawn"):
                emit(db, "job.closed", f"{company.name} — {job.title} is no longer listed; application paused.",
                     level="warn", job_id=job.id, application_id=app.id)
                notify(db, "job_closed", f"Vacancy closed: {job.title}", f"{company.name} removed this posting.",
                       dedupe_key=f"closed:{job.id}", job_id=job.id, application_id=app.id)
    company.last_status = f"ok: {stats['relevant']} relevant of {stats['fetched']}"
    return stats


MAX_JOB_ALERTS_PER_RUN = 12


def notify_new_jobs(db: Session, job_ids: list[int]) -> int:
    """Alert on the strongest new jobs. A big batch is capped and summarised instead of flooding."""
    cfg = get_setting(db, "notifications")
    min_stars = int(cfg.get("min_stars", 4))
    jobs = [j for j in (db.get(Job, jid) for jid in job_ids) if j is not None and j.eligibility != "rejected"
            and (j.visa_status == "confirmed" or j.fit_stars >= min_stars)]
    jobs.sort(key=lambda j: (j.visa_status == "confirmed", j.fit_score), reverse=True)
    count = 0
    for job in jobs[:MAX_JOB_ALERTS_PER_RUN]:
        if job.visa_status == "confirmed":
            made = notify(db, "visa_confirmed", f"Sponsorship mentioned: {job.title}",
                          f"{job.company.name} · {job.location_raw} · {job.fit_stars}★", dedupe_key=f"visa:{job.id}", job_id=job.id)
        else:
            made = notify(db, "high_fit", f"{job.fit_stars}★ match: {job.title}",
                          f"{job.company.name} · {job.location_raw} · visa {VISA_LABEL[job.visa_status].lower()}",
                          dedupe_key=f"fit:{job.id}", job_id=job.id)
        count += 1 if made else 0
    rest = len(jobs) - MAX_JOB_ALERTS_PER_RUN
    if rest > 0:
        if notify(db, "high_fit_summary", f"{rest} more strong new matches", "Open Jobs and sort by newest to see them all.",
                  dedupe_key=f"fitsummary:{utcnow().isoformat()}"):
            count += 1
    return count


def run_discovery(db: Session, company_ids: Optional[list[int]] = None, client: Optional[PoliteClient] = None,
                  trigger: str = "schedule") -> dict:
    profile = load_profile(db)
    search_cfg = get_setting(db, "search")
    q = select(Company).where(Company.enabled.is_(True))
    if company_ids:
        q = q.where(Company.id.in_(company_ids))
    companies = list(db.scalars(q.order_by(Company.id)))
    emit(db, "discovery.started", f"Job search started across {len(companies)} sources ({trigger}).", data={"trigger": trigger})
    db.commit()
    own_client = client is None
    client = client or PoliteClient()
    totals = {"companies": len(companies), "fetched": 0, "relevant": 0, "new": 0, "updated": 0, "closed": 0, "errors": 0}
    new_ids: list[int] = []
    try:
        for c in companies:
            try:
                st = sync_company(db, c, client, profile, search_cfg)
            except Exception as e:  # one bad board must not stop the run
                db.rollback()
                log.exception("sync failed for %s", c.name)
                c = db.get(Company, c.id)
                c.fail_count += 1
                c.last_status = f"error: {type(e).__name__}: {e}"[:255]
                totals["errors"] += 1
                db.commit()
                continue
            if c.last_status.startswith("error"):
                totals["errors"] += 1
            for k in ("fetched", "relevant", "new", "updated", "closed"):
                totals[k] += st[k]
            new_ids += st["new_ids"]
            if st["new"]:
                emit(db, "discovery.jobs", f"{c.name}: {st['new']} new relevant job{'s' if st['new'] != 1 else ''} discovered.",
                     data={"company_id": c.id, **{k: st[k] for k in ("new", "updated", "closed")}})
            db.commit()
    finally:
        if own_client:
            client.close()
    alerts = notify_new_jobs(db, new_ids)
    emit(db, "discovery.completed",
         f"Search finished: {totals['new']} new, {totals['updated']} updated, {totals['closed']} closed"
         + (f", {totals['errors']} source errors" if totals["errors"] else "") + ".",
         level="warn" if totals["errors"] else "info", data={**totals, "alerts": alerts})
    runs = get_setting(db, "last_runs") or {}
    runs["discovery"] = {"at": utcnow().isoformat() + "Z", **totals}
    set_setting(db, "last_runs", runs)
    db.commit()
    totals["new_ids"] = new_ids
    return totals


def verify_job(db: Session, job: Job, client: Optional[PoliteClient] = None) -> Optional[bool]:
    """Re-check a single vacancy against the official source. Returns live state (None = unknown)."""
    adapter = ADAPTERS.get(job.provider)
    if adapter is None:
        return None
    own = client is None
    client = client or PoliteClient()
    try:
        live = adapter.is_live(client, job.company.board_token, job.external_id)
    except SourceError:
        live = None
    finally:
        if own:
            client.close()
    if live is None:
        return None
    now = utcnow()
    job.last_verified_at = now
    if live and not job.is_active:
        job.is_active, job.closed_at = True, None
    elif not live and job.is_active:
        job.is_active, job.closed_at = False, now
    apply_analysis(job, load_profile(db))
    emit(db, "verify.completed", f"Verified {job.company.name} — {job.title}: {'active' if live else 'closed'}.", job_id=job.id)
    return live


def reanalyze_all(db: Session) -> int:
    """Recompute analysis for every job (e.g. after the profile changed)."""
    profile = load_profile(db)
    n = 0
    for job in db.scalars(select(Job)):
        apply_analysis(job, profile)
        n += 1
    db.commit()
    emit(db, "analysis.completed", f"Re-scored {n} jobs against the updated profile.")
    db.commit()
    return n
