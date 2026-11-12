"""Job source adapters for public, documented ATS job-board APIs.

Each adapter is independent: add a class, register it in ADAPTERS, done.
Only official employer boards are queried, so every URL stored is the employer's own listing.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx

from .config import get_settings
from .normalize import html_to_text


@dataclass
class RawJob:
    external_id: str
    title: str
    url: str
    apply_url: str
    location: str = ""
    country_hint: str = ""
    remote_hint: Optional[bool] = None
    workplace: str = ""
    department: str = ""
    employment_type: str = ""
    description_html: str = ""
    description_text: str = ""
    posted_at: Optional[datetime] = None
    salary: dict = field(default_factory=dict)


class SourceError(Exception):
    pass


class PoliteClient:
    """httpx wrapper: identifies itself, throttles per host, bounded retries, no anti-bot tricks."""

    def __init__(self, min_interval: float = 0.6, timeout: float = 25.0, transport=None):
        self.min_interval = min_interval
        self._last: dict[str, float] = {}
        self._client = httpx.Client(
            headers={"User-Agent": get_settings().http_user_agent, "Accept": "application/json"},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )

    def get(self, url: str, retries: int = 2) -> httpx.Response:
        host = urlparse(url).netloc
        last_exc: Optional[Exception] = None
        for attempt in range(retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()
            try:
                r = self._client.get(url)
            except httpx.HTTPError as e:
                last_exc = e
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                retry_after = r.headers.get("retry-after", "")
                time.sleep(min(30.0, float(retry_after)) if retry_after.isdigit() else 2.0 * (attempt + 1))
                last_exc = SourceError(f"HTTP {r.status_code}")
                continue
            return r
        raise SourceError(f"request failed for {host}: {last_exc}")

    def close(self) -> None:
        self._client.close()


def _dt(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).replace(tzinfo=None)
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d
    except (ValueError, OSError):
        return None


class Adapter:
    provider = ""

    def fetch(self, client: PoliteClient, token: str) -> list[RawJob]:
        raise NotImplementedError

    def board_name(self, client: PoliteClient, token: str) -> Optional[str]:
        return None

    def is_live(self, client: PoliteClient, token: str, external_id: str) -> Optional[bool]:
        """True/False when the official API answers; None when it could not be determined."""
        raise NotImplementedError

    def form_url(self, token: str, external_id: str, job_url: str) -> str:
        return job_url


class Greenhouse(Adapter):
    provider = "greenhouse"
    base = "https://boards-api.greenhouse.io/v1/boards"

    def fetch(self, client, token):
        r = client.get(f"{self.base}/{token}/jobs?content=true")
        if r.status_code == 404:
            raise SourceError("board not found")
        if r.status_code != 200:
            raise SourceError(f"HTTP {r.status_code}")
        out = []
        for j in r.json().get("jobs", []):
            html = j.get("content") or ""
            offices = j.get("offices") or []
            country_hint = ""
            for o in offices:
                loc = (o.get("location") or "")
                if loc:
                    country_hint = loc.split(",")[-1].strip()
                    break
            pay = ""
            for pr in j.get("pay_input_ranges") or []:
                if pr.get("min_cents") and pr.get("max_cents"):
                    pay = {"text": f"{pr.get('currency_type','')} {pr['min_cents']//100:,}–{pr['max_cents']//100:,}",
                           "min": pr["min_cents"] / 100, "max": pr["max_cents"] / 100, "currency": pr.get("currency_type", "")}
                    break
            out.append(RawJob(
                external_id=str(j["id"]),
                title=(j.get("title") or "").strip(),
                url=j.get("absolute_url") or "",
                apply_url=j.get("absolute_url") or "",
                location=((j.get("location") or {}).get("name") or "").strip(),
                country_hint=country_hint,
                department=", ".join(d.get("name", "") for d in (j.get("departments") or []) if d.get("name")),
                description_html=html,
                description_text=html_to_text(html),
                posted_at=_dt(j.get("first_published") or j.get("updated_at")),
                salary=pay or {},
            ))
        return out

    def board_name(self, client, token):
        r = client.get(f"{self.base}/{token}")
        return r.json().get("name") if r.status_code == 200 else None

    def is_live(self, client, token, external_id):
        r = client.get(f"{self.base}/{token}/jobs/{external_id}")
        if r.status_code == 200:
            return True
        if r.status_code == 404:
            return False
        return None

    def questions(self, client, token, external_id) -> Optional[dict]:
        r = client.get(f"{self.base}/{token}/jobs/{external_id}?questions=true")
        return r.json() if r.status_code == 200 else None

    def form_url(self, token, external_id, job_url):
        return f"https://job-boards.greenhouse.io/embed/job_app?for={token}&token={external_id}"


class Lever(Adapter):
    provider = "lever"
    base = "https://api.lever.co/v0/postings"

    def fetch(self, client, token):
        r = client.get(f"{self.base}/{token}?mode=json")
        if r.status_code == 404:
            raise SourceError("board not found")
        if r.status_code != 200:
            raise SourceError(f"HTTP {r.status_code}")
        data = r.json()
        if not isinstance(data, list):
            raise SourceError("unexpected response")
        out = []
        for j in data:
            cats = j.get("categories") or {}
            parts = [j.get("description") or ""]
            for lst in j.get("lists") or []:
                parts.append(f"<h3>{lst.get('text','')}</h3><ul>{lst.get('content','')}</ul>")
            parts.append(j.get("additional") or "")
            html = "\n".join(parts)
            sr = j.get("salaryRange") or {}
            salary = {}
            if sr.get("min") and sr.get("max"):
                salary = {"text": f"{sr.get('currency','')} {int(sr['min']):,}–{int(sr['max']):,}" + (f" / {sr['interval']}" if sr.get("interval") else ""),
                          "min": float(sr["min"]), "max": float(sr["max"]), "currency": sr.get("currency", "")}
            locs = cats.get("allLocations") or ([cats["location"]] if cats.get("location") else [])
            out.append(RawJob(
                external_id=str(j["id"]),
                title=(j.get("text") or "").strip(),
                url=j.get("hostedUrl") or "",
                apply_url=j.get("applyUrl") or (j.get("hostedUrl") or "") + "/apply",
                location=" / ".join(locs),
                country_hint=j.get("country") or "",
                workplace=j.get("workplaceType") or "",
                department=" / ".join(x for x in (cats.get("department"), cats.get("team")) if x),
                employment_type=cats.get("commitment") or "",
                description_html=html,
                description_text=html_to_text(html),
                posted_at=_dt(j.get("createdAt")),
                salary=salary,
            ))
        return out

    def is_live(self, client, token, external_id):
        r = client.get(f"{self.base}/{token}/{external_id}")
        if r.status_code == 200:
            return True
        if r.status_code == 404:
            return False
        return None

    def form_url(self, token, external_id, job_url):
        return f"https://jobs.lever.co/{token}/{external_id}/apply"


class Ashby(Adapter):
    provider = "ashby"
    base = "https://api.ashbyhq.com/posting-api/job-board"

    def _board(self, client, token):
        r = client.get(f"{self.base}/{token}?includeCompensation=true")
        if r.status_code == 404:
            raise SourceError("board not found")
        if r.status_code != 200:
            raise SourceError(f"HTTP {r.status_code}")
        return r.json()

    def fetch(self, client, token):
        out = []
        for j in self._board(client, token).get("jobs", []):
            if j.get("isListed") is False:
                continue
            comp = j.get("compensation") or {}
            salary = {}
            summary = comp.get("scrapeableCompensationSalarySummary") or comp.get("compensationTierSummary") or ""
            for tier in comp.get("summaryComponents") or []:
                if tier.get("compensationType") == "Salary" and tier.get("minValue") and tier.get("maxValue"):
                    salary = {"text": summary or f"{tier.get('currencyCode','')} {int(tier['minValue']):,}–{int(tier['maxValue']):,}",
                              "min": float(tier["minValue"]), "max": float(tier["maxValue"]), "currency": tier.get("currencyCode") or ""}
                    break
            addr = ((j.get("address") or {}).get("postalAddress") or {})
            locs = [j.get("location") or ""] + [s.get("location", "") for s in (j.get("secondaryLocations") or [])]
            html = j.get("descriptionHtml") or ""
            out.append(RawJob(
                external_id=str(j["id"]),
                title=(j.get("title") or "").strip(),
                url=j.get("jobUrl") or "",
                apply_url=j.get("applyUrl") or (j.get("jobUrl") or "") + "/application",
                location=" / ".join(l for l in locs if l),
                country_hint=addr.get("addressCountry") or "",
                remote_hint=bool(j.get("isRemote")) or None,
                workplace=j.get("workplaceType") or "",
                department=" / ".join(x for x in (j.get("department"), j.get("team")) if x),
                employment_type=j.get("employmentType") or "",
                description_html=html,
                description_text=j.get("descriptionPlain") or html_to_text(html),
                posted_at=_dt(j.get("publishedAt")),
                salary=salary,
            ))
        return out

    def is_live(self, client, token, external_id):
        try:
            jobs = self._board(client, token).get("jobs", [])
        except SourceError:
            return None
        return any(str(j.get("id")) == str(external_id) and j.get("isListed") is not False for j in jobs)

    def form_url(self, token, external_id, job_url):
        return f"https://jobs.ashbyhq.com/{token}/{external_id}/application"


ADAPTERS: dict[str, Adapter] = {a.provider: a for a in (Greenhouse(), Lever(), Ashby())}
