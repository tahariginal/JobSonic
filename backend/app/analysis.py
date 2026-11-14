"""Deterministic eligibility, visa intelligence and fit scoring.

Every finding carries a `kind`:
  verified   - a direct quote / structured field from the official posting
  unverified - information we could not find evidence for
  ai         - an interpretation produced by the optional AI step (never by this module)
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from .normalize import extract_years, sentences, title_level
from .schemas import ProfileData

# ---------------------------------------------------------------- visa patterns

NOT_SUPPORTED = [
    r"(?:not|un)\s*able to (?:offer|provide|support)?\s*(?:visa\s*)?sponsor",
    r"unable to (?:offer |provide )?(?:visa |work )?(?:sponsorship|sponsor)",
    r"(?:do|does|can|will|are|is)\s*(?:not|n't|n’t)\s*(?:currently\s*|be able to\s*)?(?:offer|provide|sponsor|support)\w*\s*(?:any\s*)?(?:visa|work|employment|immigration|sponsorship)",
    r"cannot (?:offer|provide|sponsor)\b",
    r"can(?:'|’)t (?:offer|provide|sponsor)\b",
    r"no (?:visa |work permit )?sponsorship",
    r"sponsorship (?:is |will )?(?:not|n't|unavailable)\s*(?:be\s*)?(?:available|offered|provided|possible)?",
    r"without (?:the need for |requiring |need of |any )?(?:visa |employer |company )?sponsorship",
    r"(?:must|need to|should) (?:already |currently )?(?:have|hold|possess|be)\s*(?:the |a |an |existing |valid |full |unrestricted )*(?:right to work|work authori[sz]ation|work permit|legally authori[sz]ed|eligible to work|authori[sz]ed to work)",
    r"(?:existing|valid|current|unrestricted|permanent)\s+(?:right to work|work authori[sz]ation|work permit)",
    r"(?:us|u\.s\.|united states) (?:citizen|citizenship|person)s? (?:only|required|is required)",
    r"(?:visa|sponsorship|work permit|immigration)\s*(?:support|assistance|sponsorship)?\s*(?:is|are|will be|can be)?\s*(?:not|n't)\s*(?:be\s*)?(?:offered|available|provided|possible|supported)",
    r"(?:relocation|visa)\s*(?:or|and|/)\s*(?:visa|relocation)\s*(?:support|assistance|sponsorship)\s*(?:is|are)\s*not",
    r"not (?:eligible|open) for (?:visa )?sponsorship",
]
CONDITIONAL = [
    r"sponsorship (?:may|might|can|could) be (?:available|considered|offered|possible|provided)",
    r"(?:may|might|can|could) (?:be able to )?(?:offer|provide|consider|sponsor)\s*(?:visa\s*)?sponsor",
    r"case[- ]by[- ]case",
    r"sponsorship (?:is )?(?:available |offered |considered )?(?:for|on) (?:certain|some|select|specific|eligible|exceptional)",
    r"(?:depending|dependent|subject to|contingent) (?:on|upon)[^.]{0,60}(?:visa|sponsorship|work permit)",
    r"visa sponsorship[^.]{0,40}(?:considered|possible|potentially)",
    r"(?:open to|consider)\w*\s*(?:visa\s*)?sponsor",
]
CONFIRMED = [
    r"visa sponsorship (?:is |are |will be )?(?:available|provided|offered|included|supported)",
    r"(?:we|company|employer)?\s*(?:do |will |can |happily |gladly |are able to |are happy to )?(?:offer|provide|give)s?\s*(?:full\s*)?(?:visa|work permit|immigration)\s*(?:and relocation\s*)?(?:sponsorship|support|assistance)",
    r"(?:we|company)\s*(?:do |will |can |happily |gladly )?sponsor\s*(?:work\s*)?(?:visas?|work permits?)",
    r"(?:we|company)(?:'ll| will)? (?:support|help|assist)\s*(?:you\s*)?(?:with\s*)?(?:your\s*|the\s*)?(?:visa|work permit|immigration)",
    r"(?:visa|immigration|work permit)\s*(?:and|&|/)\s*relocation\s*(?:support|assistance|package|help)",
    r"relocation\s*(?:and|&|/)\s*(?:visa|immigration|work permit)\s*(?:support|assistance|sponsorship|package|help)",
    r"(?:visa|work permit|immigration)\s*(?:support|assistance|help)\b",
    r"sponsor(?:ship)?\s*(?:of|for)\s*(?:your\s*)?(?:work\s*)?(?:visa|permit)",
    r"blue card",
    r"skilled worker visa",
    r"highly skilled migrant|kennismigrant",
]
RELOCATION = [
    r"relocation (?:assistance|support|package|bonus|allowance|budget|help|stipend|benefit)",
    r"(?:help|assist|support)\w*\s*(?:you\s*)?(?:with\s*)?(?:your\s*)?relocat",
    r"relocation is (?:provided|offered|supported|covered)",
    r"we (?:will |'ll )?relocate you",
]
NO_RELOCATION = [r"no relocation", r"relocation (?:is |assistance is )?not (?:provided|offered|available)", r"(?:do|does) not (?:offer|provide) relocation"]
REMOTE_ANYWHERE = [
    r"(?:work|working|hire|hiring|located|based)\s*(?:remotely\s*)?(?:from\s*)?anywhere in the world",
    r"remote[- ]first[^.]{0,40}(?:worldwide|globally|anywhere)",
    r"fully remote[^.]{0,60}(?:worldwide|globally|any country|anywhere)",
    r"(?:hire|hiring|work)\w*\s*(?:people\s*)?(?:from\s*)?(?:all over|around|across) the (?:world|globe)",
    r"any(?:where| country| time ?zone)[^.]{0,30}(?:in the world|on earth|worldwide)",
]
REMOTE_RESTRICTED = [
    r"(?:must|need to|should) (?:be |reside |live )(?:based |located |resident )?(?:in|within) (?:the )?(?!any)[A-Z][\w .,/]{2,40}",
    r"remote (?:within|in) (?:the )?(?:us|u\.s\.|united states|uk|eu|europe|canada|germany)",
    r"only (?:hire|hiring|able to hire|employ) (?:in|within|from)",
]

_VISA_CONTEXT = re.compile(r"visa|sponsor|work permit|work authori[sz]|right to work|authori[sz]ed to work|eligible to work|legally (?:work|authori)|"
                           r"immigration|blue card|kennismigrant|skilled migrant|citizen|residen(?:ce|cy) permit|relocat", re.I)
_OFF_TOPIC = re.compile(r"export (?:control|licen[sc]e|law|regulation|administration)|sponsor(?:ed|ing|s)? (?:an? )?(?:event|conference|meetup|hackathon|team|charit|program|project|initiative)|"
                        r"executive sponsor|project sponsor|sponsor(?:ed)? by", re.I)
_PREFERENCE = re.compile(r"prioriti[sz]|prefer|particularly interested|preference (?:will be|is) given|ideally|encourage", re.I)
_NEGATION = re.compile(r"\b(?:not|no|unable|cannot|can(?:'|’)t|won(?:'|’)t|don(?:'|’)t|doesn(?:'|’)t|isn(?:'|’)t|aren(?:'|’)t|without|unfortunately|neither|nor)\b", re.I)
CLEARANCE = re.compile(r"security clearance|\b(?:ts/sci|top secret|secret clearance|sc clearance|dv clearance|public trust)\b", re.I)
CLEARANCE_HARD = re.compile(r"active|current|must|required|requires|hold|possess|eligib|obtain|maintain|ability to", re.I)

DEGREE_REQ = re.compile(
    r"\b(bachelor(?:'|’)?s?|b\.?sc\.?|b\.?s\.?|b\.?a\.?|b\.?eng\.?|master(?:'|’)?s?|m\.?sc\.?|m\.?s\.?|ph\.?d\.?|"
    r"university degree|college degree|degree in|diploma in|licence|undergraduate degree)\b",
    re.I,
)
DEGREE_ALT = re.compile(
    r"equivalent (?:practical |work |professional |industry |relevant )?(?:experience|background|training)|"
    r"equivalent combination|or equivalent|or related experience|or comparable|or similar (?:experience|qualification)|"
    r"(?:degree|diploma)[^.]{0,30}(?:not required|is a plus|preferred|nice to have|or bootcamp)|"
    r"no degree (?:required|needed)|self[- ]taught|bootcamp|non[- ]traditional",
    re.I,
)
PHD_REQ = re.compile(r"\bph\.?d\.?\b[^.]{0,40}\b(required|must)\b|\b(required|must)\b[^.]{0,40}\bph\.?d\.?\b", re.I)
UNPAID = re.compile(r"\b(unpaid|volunteer position|no compensation|without pay|equity[- ]only)\b", re.I)
ENROLLED = re.compile(r"(?:currently |must be )?enrolled (?:in|at) (?:a |an )?(?:university|college|degree|bachelor|master)|pursuing (?:a |an )?(?:bachelor|master|degree|phd)", re.I)

LANGS = ["german", "french", "dutch", "spanish", "portuguese", "italian", "japanese", "korean", "mandarin", "chinese",
         "arabic", "polish", "czech", "swedish", "danish", "norwegian", "finnish", "turkish", "hebrew", "russian"]
LANG_REQ = re.compile(
    r"\b(?:fluen\w+|proficien\w+|native|business[- ]level|professional[- ]level|c1|c2|b2|speak\w*|command of|excellent|strong|very good)\b"
    r"[^.\n]{0,60}\b(" + "|".join(LANGS) + r")\b|\b(" + "|".join(LANGS) + r")\b[^.\n]{0,40}"
    r"\b(?:required|mandatory|is a must|fluen\w+|proficien\w+|native|c1|c2|b2|skills)\b",
    re.I,
)
LANG_SOFT = re.compile(r"plus|nice to have|bonus|advantage|preferred|beneficial|desirable|not required|optional|or english|is a must: english", re.I)

TECH_LEXICON = [
    "python", "java", "javascript", "typescript", "go", "golang", "rust", "c++", "c#", "c", "ruby", "php", "kotlin", "swift",
    "scala", "elixir", "sql", "bash", "node.js", "node", "react", "react native", "next.js", "vue", "angular", "svelte",
    "django", "flask", "fastapi", "spring", "rails", "laravel", ".net", "express", "graphql", "rest", "grpc", "api", "apis",
    "microservices", "docker", "kubernetes", "terraform", "aws", "gcp", "azure", "linux", "unix", "git", "ci/cd",
    "postgresql", "postgres", "mysql", "mongodb", "redis", "kafka", "rabbitmq", "elasticsearch", "sqlite",
    "llm", "llms", "rag", "mcp", "ai agents", "ai agent", "llm agents", "agentic", "langchain", "openai", "anthropic", "claude",
    "prompt engineering", "tool calling", "function calling", "machine learning", "pytorch", "tensorflow", "embeddings",
    "vector database", "fine-tuning", "nlp", "computer vision", "automation", "orchestration", "backend", "full-stack",
    "fullstack", "frontend", "mobile", "ios", "android", "flutter", "unity", "vr", "ar", "opengl", "embedded",
    "distributed systems", "networking", "multithreading", "concurrency", "algorithms", "data structures",
    "playwright", "selenium", "html", "css", "tailwind", "websockets", "oauth", "system design", "testing",
]
ALIASES = {
    "golang": "go", "node": "node.js", "postgres": "postgresql", "apis": "api", "llms": "llm", "fullstack": "full-stack",
    "ai agent": "ai agents", "llm agents": "ai agents", "agentic": "ai agents", "function calling": "tool calling",
    "backend development": "backend", "backend engineering": "backend", "full-stack development": "full-stack",
    "mobile applications": "mobile", "software systems": "system design", "applied ai": "llm",
}


def _canon(term: str) -> str:
    t = term.strip().lower()
    return ALIASES.get(t, t)


def _tech_in(text: str) -> set[str]:
    low = " " + (text or "").lower() + " "
    found = set()
    for term in TECH_LEXICON:
        if re.search(rf"(?<![\w+#.]){re.escape(term)}(?![\w+#])", low):
            found.add(_canon(term))
    return found


def _first_match(patterns: list[str], sents: list[str]) -> Optional[tuple[str, str]]:
    for s in sents:
        for p in patterns:
            if re.search(p, s, re.I):
                return s[:400], p
    return None


def _all_matches(patterns: list[str], sents: list[str], cap: int = 3) -> list[str]:
    out = []
    for s in sents:
        if any(re.search(p, s, re.I) for p in patterns):
            out.append(s[:400])
            if len(out) >= cap:
                break
    return out


def analyze_visa(description: str, *, country: str, remote_mode: str, remote_scope: str,
                 location_raw: str, source_url: str, profile: ProfileData, now: datetime) -> dict:
    sents = sentences(description or "")
    checked = now.isoformat() + "Z"
    authorized = {c.lower() for c in profile.work_authorization.authorized_countries}
    ev: list[dict] = []

    def add(quote: str, explanation: str, kind: str = "verified") -> None:
        ev.append({"quote": quote, "explanation": explanation, "source_url": source_url, "checked_at": checked, "kind": kind})

    all_sents = sents
    # only sentences that are actually about immigration / work authorization count as evidence
    sents = [s for s in sents if _VISA_CONTEXT.search(s) and not _OFF_TOPIC.search(s)]
    neg_all = _all_matches(NOT_SUPPORTED, sents, 6)
    # "we prioritise / prefer applicants with a right to work" is a preference, not an exclusion
    soft = [s for s in neg_all if _PREFERENCE.search(s)]
    neg = [s for s in neg_all if s not in soft][:3]
    cond = (_all_matches(CONDITIONAL, sents) + soft)[:3]
    # a "positive" sentence that contains a negation is not confirmation
    pos = [s for s in _all_matches(CONFIRMED, sents) if s not in neg_all and s not in cond and not _NEGATION.search(s)]

    if country and country.lower() in authorized:
        status = "not_required"
        add("", f"The role is located in {country}, where the candidate profile lists existing work authorization.", "verified")
    elif neg:
        status = "not_supported"
        for q in neg:
            add(q, "The posting states that existing work authorization is required or that sponsorship is not offered.")
    elif cond:
        status = "conditional"
        for q in cond:
            add(q, "Local work authorization is preferred; sponsorship is not ruled out but not promised." if q in soft
                else "The posting says sponsorship may be considered; it is not guaranteed.")
    elif pos:
        status = "confirmed"
        for q in pos:
            add(q, "The posting explicitly mentions visa / work-permit support for this vacancy.")
    else:
        status = "unverified"
        add("", "No statement about visa sponsorship or work authorization was found in the official posting.", "unverified")

    # relocation is tracked separately: it never upgrades the visa status
    rel_neg = _all_matches(NO_RELOCATION, sents, 1)
    rel_pos = _all_matches(RELOCATION, sents, 2)
    relocation, rel_ev = "unverified", []
    if rel_neg:
        relocation = "no"
        rel_ev = [{"quote": q, "source_url": source_url, "checked_at": checked, "kind": "verified"} for q in rel_neg]
    elif rel_pos:
        relocation = "yes"
        rel_ev = [{"quote": q, "source_url": source_url, "checked_at": checked, "kind": "verified"} for q in rel_pos]

    # remote-from-Morocco
    remote_ma = "unverified"
    if remote_mode == "remote":
        anywhere = _all_matches(REMOTE_ANYWHERE, all_sents, 1)
        restricted = _all_matches(REMOTE_RESTRICTED, all_sents, 1)
        if remote_scope == "Worldwide" or anywhere:
            remote_ma = "likely"
            add(anywhere[0] if anywhere else location_raw,
                "Remote scope is described as worldwide. Morocco is not named explicitly, so this still needs confirmation.",
                "verified")
        elif remote_scope and remote_scope not in ("EMEA", "Africa"):
            remote_ma = "no"
            add(location_raw, f"Remote work is limited to {remote_scope}; nothing indicates Morocco is allowed.", "verified")
        elif remote_scope in ("EMEA", "Africa"):
            add(location_raw, f"Remote scope is {remote_scope}; whether Morocco is included is not stated.", "unverified")
        if restricted and remote_ma != "likely":
            remote_ma = "no" if remote_ma == "unverified" and country and country.lower() not in authorized else remote_ma
            add(restricted[0], "The posting restricts where remote employees may be based.", "verified")
    elif country and country.lower() in authorized:
        remote_ma = "n/a"

    return {
        "visa_status": status,
        "visa_evidence": ev,
        "relocation": relocation,
        "relocation_evidence": rel_ev,
        "remote_from_morocco": remote_ma,
    }


def analyze_eligibility(*, title: str, description: str, employment_type: str, visa: dict, profile: ProfileData,
                        source_url: str, is_active: bool = True) -> dict:
    reasons: list[dict] = []
    verdict = "eligible"
    max_years = profile.preferences.max_years_experience or 2

    def add(code: str, text: str, kind: str, severity: str, quote: str = "") -> None:
        nonlocal verdict
        reasons.append({"code": code, "text": text, "kind": kind, "severity": severity, "quote": quote, "source_url": source_url})
        if severity == "reject":
            verdict = "rejected"
        elif severity == "review" and verdict != "rejected":
            verdict = "needs_review"

    level = title_level(title)
    years, yquote = extract_years(description)

    if not is_active:
        add("closed", "The vacancy is no longer listed on the official careers source.", "verified", "reject")
    if level == "senior":
        add("senior_title", f"Title indicates a senior-level role (“{title}”).", "verified", "reject")
    if years is not None:
        if years > max_years + 1:
            add("years", f"Requires about {years:g}+ years of experience (limit {max_years:g}).", "verified", "reject", yquote)
        elif years > max_years:
            add("years_borderline", f"Asks for about {years:g} years of experience, slightly above the {max_years:g}-year target.", "verified", "review", yquote)
        else:
            add("years_ok", f"Stated experience requirement ({years:g} years) is within range.", "verified", "ok", yquote)
            if level == "unknown":
                level = "junior"
    if level == "mid":
        add("mid_title", "Title suggests a mid-level role; junior suitability is not confirmed.", "verified", "review")
    if level == "intern":
        add("internship", "This is an internship / student position rather than a regular junior role.", "verified", "review")
        m = ENROLLED.search(description or "")
        if m:
            add("enrolled", "May require current enrolment in a university degree programme.", "verified", "review",
                _sentence_with(description, m.start()))
    if level == "unknown" and years is None:
        add("level_unknown", "The posting does not state an experience level or years required.", "unverified", "review")
    if level == "junior" and years is None:
        add("junior_title", "Title indicates an entry-level / junior role.", "verified", "ok")

    if UNPAID.search(description or "") or UNPAID.search(employment_type or ""):
        m = UNPAID.search(description or "")
        add("unpaid", "The role appears to be unpaid.", "verified", "reject", _sentence_with(description, m.start()) if m else "")

    cm = CLEARANCE.search(description or "")
    if cm:
        sent = _sentence_with(description, cm.start())
        if CLEARANCE_HARD.search(sent) and not re.search(r"not required|no clearance|nice to have|a plus|preferred but", sent, re.I):
            add("clearance", "Requires a government security clearance, which normally needs local citizenship.", "verified", "reject", sent)
        else:
            add("clearance_mentioned", "A security clearance is mentioned; check whether it is required.", "verified", "review", sent)

    # education
    m = PHD_REQ.search(description or "")
    if m:
        add("phd", "A PhD appears to be required.", "verified", "reject", _sentence_with(description, m.start()))
    else:
        dm = DEGREE_REQ.search(description or "")
        if dm:
            sent = _sentence_with(description, dm.start())
            window = (description or "")[max(0, dm.start() - 200): dm.end() + 260]
            if DEGREE_ALT.search(window):
                add("degree_alt", "A degree is mentioned, with equivalent experience or alternatives accepted.", "verified", "ok", sent)
            else:
                add("degree", "A conventional degree is mentioned without a stated alternative. "
                    "The 42 Common Core is not assumed to be equivalent.", "verified", "review", sent)

    # languages
    confirmed_langs = {l.language.strip().lower() for l in profile.languages if l.language.strip()}
    seen_lang: set[str] = set()
    for lm in LANG_REQ.finditer(description or ""):
        lang = (lm.group(1) or lm.group(2) or "").lower()
        if lang == "chinese":
            lang = "mandarin" if "mandarin" in confirmed_langs else "chinese"
        if not lang or lang in seen_lang or lang in confirmed_langs:
            continue
        seen_lang.add(lang)
        sent = _sentence_with(description, lm.start())
        if LANG_SOFT.search(sent):
            add("language_soft", f"{lang.title()} is mentioned as a plus (not confirmed in the profile).", "verified", "ok", sent)
        else:
            add("language", f"{lang.title()} skills appear to be required and are not confirmed in the profile.", "verified", "review", sent)

    # work authorization
    vs = visa["visa_status"]
    if vs == "not_supported":
        if visa.get("remote_from_morocco") == "likely":
            add("auth_remote", "Sponsorship is not offered, but the role may be workable remotely from Morocco.", "verified", "review")
        else:
            q = visa["visa_evidence"][0]["quote"] if visa["visa_evidence"] else ""
            add("no_sponsorship", "Requires existing local work authorization or excludes sponsorship.", "verified", "reject", q)
    elif vs == "unverified":
        add("visa_unverified", "Visa sponsorship is not mentioned in the posting.", "unverified", "info")
    elif vs == "conditional":
        add("visa_conditional", "Sponsorship may be considered case by case.", "verified", "info")
    elif vs == "confirmed":
        add("visa_confirmed", "The posting explicitly mentions visa / work-permit support.", "verified", "ok")
    elif vs == "not_required":
        add("visa_not_required", "No sponsorship needed for this location.", "verified", "ok")

    return {"eligibility": verdict, "eligibility_reasons": reasons, "experience_level": level, "min_years": years}


def _sentence_with(text: str, pos: int) -> str:
    text = text or ""
    start = max(text.rfind("\n", 0, pos), text.rfind(". ", 0, pos)) + 1
    ends = [e for e in (text.find("\n", pos), text.find(". ", pos)) if e != -1]
    end = min(ends) + 1 if ends else len(text)
    return text[start:end].strip(" -•")[:400]


REGION_WEIGHT = {"europe": 1.0, "asia": 0.85, "middle_east": 0.85, "north_america": 0.6, "africa": 0.5, "oceania": 0.5, "latam": 0.3, "": 0.4}
INTEREST_FAMILIES = {
    "applied_ai": ["applied ai", "ai agents", "mcp", "rag", "tool calling", "orchestration"],
    "backend": ["backend engineering", "backend development", "apis"],
    "fullstack": ["full-stack development", "product engineering"],
    "mobile": ["mobile applications"],
    "automation": ["automation", "orchestration", "tool calling"],
    "platform": ["software systems", "orchestration"],
    "software": ["product engineering", "software systems"],
    "frontend": ["full-stack development"],
}


def score_fit(*, title: str, description: str, role_family: str, level: str, min_years: Optional[float],
              eligibility: str, visa: dict, country: str, region: str, remote_mode: str,
              salary_min: Optional[float], salary_currency: str, profile: ProfileData) -> dict:
    prof_terms = {_canon(s) for s in profile.skills} | {_canon(s) for s in profile.interests}
    for pr in profile.projects:
        prof_terms |= {_canon(t) for t in pr.tech}
    job_tech = _tech_in(f"{title}\n{description}")
    matched = sorted(job_tech & prof_terms)
    missing = sorted(job_tech - prof_terms)
    skills = 0.5 if not job_tech else min(1.0, len(matched) / max(1, min(len(job_tech), 6)))

    interests_low = {i.lower() for i in profile.interests} | {s.lower() for s in profile.skills}
    fam_hits = [k for k in INTEREST_FAMILIES.get(role_family, []) if k in interests_low]
    interest = 1.0 if fam_hits else 0.4
    if role_family != "applied_ai" and re.search(r"\b(llm|ai agent|agentic|rag|mcp)\b", (description or "").lower()) and \
            interests_low & {"ai agents", "rag", "mcp", "applied ai"}:
        interest = min(1.0, interest + 0.3)

    lvl = {"junior": 1.0, "intern": 0.55, "unknown": 0.5, "mid": 0.3, "senior": 0.0}.get(level, 0.5)
    if min_years is not None:
        max_y = profile.preferences.max_years_experience or 2
        lvl = 1.0 if min_years <= max(1, max_y - 1) else 0.85 if min_years <= max_y else 0.35 if min_years <= max_y + 1 else 0.0

    vs = visa["visa_status"]
    visa_score = {"confirmed": 1.0, "not_required": 1.0, "conditional": 0.7, "unverified": 0.35, "not_supported": 0.0}[vs]
    if visa.get("remote_from_morocco") == "likely":
        visa_score = max(visa_score, 0.85)

    pref = {c.lower() for c in profile.preferences.countries}
    if pref and country:
        loc = 1.0 if country.lower() in pref else 0.5
    elif remote_mode == "remote" and visa.get("remote_from_morocco") == "likely":
        loc = 1.0
    else:
        loc = REGION_WEIGHT.get(region, 0.4)
        if region == "north_america" and vs in ("confirmed", "conditional"):
            loc = 0.85

    sal = 0.5
    sal_known = salary_min is not None
    if (sal_known and profile.preferences.salary_min and profile.preferences.salary_period == "year"
            and profile.preferences.salary_context_verified
            and profile.preferences.salary_currency.upper() == (salary_currency or "").upper()):
        sal = 1.0 if salary_min >= profile.preferences.salary_min else 0.2
    elif sal_known:
        sal = 0.7

    weights = {"skills": 28, "interest": 14, "level": 22, "visa": 22, "location": 9, "salary": 5}
    parts = {"skills": skills, "interest": interest, "level": lvl, "visa": visa_score, "location": loc, "salary": sal}
    score = sum(weights[k] * parts[k] for k in weights)
    if eligibility == "needs_review":
        score -= 6
    stars = 5 if score >= 78 else 4 if score >= 64 else 3 if score >= 50 else 2 if score >= 36 else 1
    # a role that needs sponsorship with no evidence of it cannot be a top match
    if vs == "unverified" and visa.get("remote_from_morocco") != "likely":
        stars = min(stars, 4)
    if eligibility == "rejected":
        stars = 1

    bits = []
    fam_label = {"applied_ai": "applied-AI", "backend": "backend", "fullstack": "full-stack", "mobile": "mobile",
                 "automation": "automation", "platform": "platform", "software": "software", "frontend": "frontend"}.get(role_family, role_family)
    if matched:
        bits.append(f"{'Strong' if skills >= 0.6 else 'Partial'} {fam_label} match ({', '.join(matched[:4])})")
    elif job_tech:
        bits.append(f"{fam_label.capitalize()} role; none of its listed technologies ({', '.join(missing[:3])}) are in your profile yet")
    else:
        bits.append(f"{fam_label.capitalize()} role with no specific stack listed")
    bits.append({
        "junior": "entry-level experience accepted", "intern": "internship / student position",
        "unknown": "experience level not stated", "mid": "looks mid-level", "senior": "senior-level",
    }[level] if min_years is None else f"asks for ~{min_years:g} yr experience")
    bits.append({
        "confirmed": "visa support explicitly mentioned", "not_required": "no sponsorship needed",
        "conditional": "sponsorship considered case by case", "unverified": "sponsorship not mentioned",
        "not_supported": "sponsorship not offered",
    }[vs] + (" (remote worldwide)" if visa.get("remote_from_morocco") == "likely" else ""))
    if eligibility == "rejected":
        bits.append("fails a hard eligibility rule")
    reason = "; ".join(bits) + "."
    reason = reason[0].upper() + reason[1:]

    return {
        "fit_score": round(score, 1),
        "fit_stars": stars,
        "fit_reason": reason,
        "fit_breakdown": {
            "components": {k: round(parts[k], 2) for k in parts},
            "weights": weights,
            "matched_skills": matched,
            "unmatched_technologies": missing[:12],
        },
    }
