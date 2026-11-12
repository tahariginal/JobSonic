"""Deterministic normalisation of raw ATS postings: text, role family, seniority, location, salary."""
from __future__ import annotations

import hashlib
import html as html_lib
import re
from typing import Optional

from bs4 import BeautifulSoup

# ---------------------------------------------------------------- text

def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    if "&lt;" in raw and "<" not in raw:
        raw = html_lib.unescape(raw)
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for li in soup.find_all("li"):
        li.insert_before("\n- ")
    for br in soup.find_all(["br", "p", "div", "h1", "h2", "h3", "h4", "h5", "ul", "ol"]):
        br.insert_before("\n")
    text = soup.get_text()
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip(" -•\t") for p in parts if p and len(p.strip()) > 2]


def fingerprint(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(re.sub(r"\s+", " ", (p or "")).strip().lower().encode())
        h.update(b"\x1f")
    return h.hexdigest()


def canonical_url(url: str) -> str:
    url = (url or "").strip()
    url = re.sub(r"[?#].*$", "", url) if "gh_jid" not in url else re.sub(r"#.*$", "", url)
    return url.rstrip("/")


# ---------------------------------------------------------------- role / seniority

ENGINEER_WORD = re.compile(r"\b(engineer|engineering|developer|programmer|swe|sde)\b", re.I)
EXCLUDE_TITLE = re.compile(
    r"\b(sales|pre-?sales|account|recruit|talent|hardware|mechanical|electrical|civil|manufacturing|"
    r"technician|field|customer success|support engineer|technical support|solutions? (engineer|architect|consultant)|"
    r"manager|director|head of|vp|vice president|chief|designer|marketing|finance|legal|counsel|"
    r"rf|asic|fpga|silicon|firmware|optical|chemical|process engineer|quality engineer|test engineer|"
    r"network engineer|security engineer|data engineer|data scientist|analyst|research scientist|"
    r"site reliability|sre|devrel|developer advocate|developer relations|engineering program)\b",
    re.I,
)
ROLE_FAMILIES: list[tuple[str, re.Pattern]] = [
    ("applied_ai", re.compile(r"\b(ai|a\.i\.|ml|machine learning|llm|agent|agents|agentic|genai|generative|applied ai)\b", re.I)),
    ("mobile", re.compile(r"\b(mobile|ios|android|react native|flutter)\b", re.I)),
    ("fullstack", re.compile(r"\bfull[- ]?stack\b", re.I)),
    ("backend", re.compile(r"\b(back[- ]?end|server[- ]side|api)\b", re.I)),
    ("automation", re.compile(r"\b(automation|integration|integrations|tooling)\b", re.I)),
    ("platform", re.compile(r"\b(platform|infrastructure|devops|cloud|systems)\b", re.I)),
    ("frontend", re.compile(r"\bfront[- ]?end\b", re.I)),
    ("software", re.compile(r"\b(software|product|graduate|new grad|junior|developer|engineer)\b", re.I)),
]

SENIOR = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|leader|architect|distinguished|expert|fellow|iii|iv|l[5-9]|"
    r"tech lead|team lead)\b",
    re.I,
)
MID = re.compile(r"\b(mid[- ]?level|intermediate|ii|l4|experienced|medior)\b", re.I)
INTERN = re.compile(r"\b(intern|internship|working student|werkstudent|stagiaire|apprentice|apprenticeship|co-?op|praktikum|alternance|thesis)\b", re.I)
JUNIOR = re.compile(
    r"\b(junior|jr\.?|graduate|new grad|new graduate|entry[- ]level|early[- ]career|early in career|"
    r"associate|trainee|university grad|campus|grad)\b",
    re.I,
)


def is_relevant_title(title: str, extra: Optional[list[str]] = None, exclude: Optional[list[str]] = None) -> bool:
    t = title or ""
    low = t.lower()
    for kw in exclude or []:
        if kw and kw.lower() in low:
            return False
    for kw in extra or []:
        if kw and kw.lower() in low:
            return True
    if not ENGINEER_WORD.search(t):
        return False
    if EXCLUDE_TITLE.search(t):
        return False
    return True


def role_family(title: str) -> str:
    for name, pat in ROLE_FAMILIES:
        if pat.search(title or ""):
            return name
    return "software"


_NUM_LEVEL = re.compile(r"\b(?:engineer|developer|swe|sde|programmer)\s*[,-]?\s*(?:level\s*)?([1-6])\b|\b(?:level|grade)\s*([1-6])\b", re.I)


def title_level(title: str) -> str:
    t = title or ""
    if SENIOR.search(t):
        return "senior"
    nm = _NUM_LEVEL.search(t)
    if nm:  # "Software Engineer 3", "Engineer II" style ladders
        n = int(nm.group(1) or nm.group(2))
        return "senior" if n >= 3 else "mid" if n == 2 else "junior"
    if INTERN.search(t):
        return "intern"
    if JUNIOR.search(t):
        return "junior"
    if MID.search(t):
        return "mid"
    return "unknown"


_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "ten": 10}
_YEARS = re.compile(
    r"(?P<a>\d{1,2}|one|two|three|four|five|six|seven|eight|ten)\s*(?P<plus>\+)?\s*"
    r"(?:(?:-|–|—|to)\s*(?P<b>\d{1,2})\s*\+?\s*)?"
    r"(?:years?|yrs?)(?!\s*old)",
    re.I,
)
_EXP_CONTEXT = re.compile(r"experience|professional|industry|working|hands-on|track record|background|in a similar|as a", re.I)


def extract_years(text: str) -> tuple[Optional[float], str]:
    """Return (minimum years of experience required, quoted sentence) or (None, '')."""
    best: Optional[float] = None
    quote = ""
    for sent in sentences(text or ""):
        for m in _YEARS.finditer(sent):
            if not _EXP_CONTEXT.search(sent):
                continue
            a = m.group("a").lower()
            n = float(_NUM_WORDS.get(a, 0) or (int(a) if a.isdigit() else 0))
            if n > 15 or (n <= 0 and not m.group("b")):
                continue  # "0-2 years" is a real (zero-minimum) requirement; a bare 0 is not
            if best is None or n > best:
                best = n
                quote = sent[:300]
    return best, quote


# ---------------------------------------------------------------- location

COUNTRIES: dict[str, tuple[str, str]] = {}


def _add(region: str, country: str, *aliases: str) -> None:
    for a in (country, *aliases):
        COUNTRIES[a.lower()] = (country, region)


_add("europe", "Germany", "deutschland", "berlin", "munich", "münchen", "hamburg", "cologne", "köln", "frankfurt", "stuttgart", "düsseldorf", "dusseldorf", "leipzig", "karlsruhe")
_add("europe", "Netherlands", "the netherlands", "amsterdam", "rotterdam", "utrecht", "eindhoven", "the hague", "den haag", "delft")
_add("europe", "France", "paris", "lyon", "marseille", "toulouse", "nantes", "bordeaux", "lille", "grenoble", "sophia antipolis")
_add("europe", "Austria", "vienna", "wien", "graz", "linz")
_add("europe", "Poland", "warsaw", "warszawa", "krakow", "kraków", "wroclaw", "wrocław", "gdansk", "gdańsk", "poznan", "poznań")
_add("europe", "Portugal", "lisbon", "lisboa", "porto")
_add("europe", "Spain", "madrid", "barcelona", "valencia", "malaga", "málaga", "seville")
_add("europe", "United Kingdom", "uk", "u.k.", "england", "scotland", "wales", "great britain", "london", "manchester", "edinburgh", "cambridge", "bristol", "oxford", "leeds", "glasgow", "belfast")
_add("europe", "Ireland", "dublin", "cork", "galway")
_add("europe", "Czech Republic", "czechia", "prague", "praha", "brno")
_add("europe", "Sweden", "stockholm", "gothenburg", "malmö", "malmo")
_add("europe", "Denmark", "copenhagen", "aarhus")
_add("europe", "Norway", "oslo")
_add("europe", "Finland", "helsinki", "espoo")
_add("europe", "Switzerland", "zurich", "zürich", "geneva", "lausanne", "basel", "bern")
_add("europe", "Belgium", "brussels", "antwerp", "ghent")
_add("europe", "Italy", "milan", "milano", "rome", "roma", "turin")
_add("europe", "Estonia", "tallinn")
_add("europe", "Lithuania", "vilnius", "kaunas")
_add("europe", "Latvia", "riga")
_add("europe", "Romania", "bucharest", "cluj", "cluj-napoca")
_add("europe", "Hungary", "budapest")
_add("europe", "Bulgaria", "sofia")
_add("europe", "Greece", "athens")
_add("europe", "Luxembourg")
_add("europe", "Serbia", "belgrade")
_add("europe", "Croatia", "zagreb")
_add("europe", "Cyprus", "limassol", "nicosia")
_add("europe", "Malta")
_add("europe", "Ukraine", "kyiv")
_add("europe", "Turkey", "türkiye", "istanbul", "ankara")
_add("asia", "Japan", "tokyo", "osaka", "kyoto", "fukuoka")
_add("asia", "Singapore")
_add("asia", "Malaysia", "kuala lumpur", "penang")
_add("asia", "South Korea", "korea", "seoul")
_add("asia", "India", "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "gurgaon", "gurugram", "noida", "chennai", "delhi")
_add("asia", "China", "beijing", "shanghai", "shenzhen", "hangzhou")
_add("asia", "Hong Kong")
_add("asia", "Taiwan", "taipei")
_add("asia", "Thailand", "bangkok")
_add("asia", "Vietnam", "ho chi minh", "hanoi")
_add("asia", "Indonesia", "jakarta")
_add("asia", "Philippines", "manila")
_add("middle_east", "United Arab Emirates", "uae", "u.a.e.", "dubai", "abu dhabi")
_add("middle_east", "Saudi Arabia", "ksa", "riyadh", "jeddah")
_add("middle_east", "Qatar", "doha")
_add("middle_east", "Israel", "tel aviv")
_add("middle_east", "Egypt", "cairo")
_add("middle_east", "Bahrain", "manama")
_add("middle_east", "Kuwait")
_add("middle_east", "Jordan", "amman")
_add("north_america", "United States", "usa", "u.s.", "u.s.a.", "us", "united states of america", "san francisco", "new york", "nyc", "seattle", "austin", "boston", "chicago", "los angeles", "denver", "atlanta", "palo alto", "mountain view", "sunnyvale", "san jose", "washington", "bay area", "sf", "miami", "portland", "san diego", "bellevue", "menlo park", "santa clara")
_add("north_america", "Canada", "toronto", "vancouver", "montreal", "montréal", "ottawa", "waterloo", "calgary")
_add("north_america", "Mexico", "mexico city", "guadalajara")
_add("africa", "Morocco", "maroc", "casablanca", "rabat", "marrakech", "tangier", "benguerir", "ben guerir")
_add("africa", "South Africa", "cape town", "johannesburg")
_add("africa", "Nigeria", "lagos")
_add("africa", "Kenya", "nairobi")
_add("oceania", "Australia", "sydney", "melbourne", "brisbane")
_add("oceania", "New Zealand", "auckland", "wellington")
_add("latam", "Brazil", "são paulo", "sao paulo")
_add("latam", "Argentina", "buenos aires")
_add("latam", "Colombia", "bogotá", "bogota")

_US_STATE = re.compile(r",\s*(AL|AK|AZ|AR|CA|CO|CT|DC|DE|FL|GA|HI|IA|ID|IL|IN|KS|KY|LA|MA|MD|ME|MI|MN|MO|MS|MT|NC|ND|NE|NH|NJ|NM|NV|NY|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VA|VT|WA|WI|WV|WY)\b")
_REMOTE = re.compile(r"\b(remote|anywhere|work from home|wfh|distributed|home[- ]based)\b", re.I)
_HYBRID = re.compile(r"\bhybrid\b", re.I)
_WORLDWIDE = re.compile(r"\b(worldwide|world-wide|anywhere in the world|global|globally|any country|international)\b", re.I)
_REGION_SCOPES = [
    ("EMEA", re.compile(r"\bemea\b", re.I)),
    ("Europe", re.compile(r"\b(europe|eu|european)\b", re.I)),
    ("Africa", re.compile(r"\b(africa|mena|north africa)\b", re.I)),
    ("Americas", re.compile(r"\b(americas|amer|latam|north america)\b", re.I)),
    ("APAC", re.compile(r"\b(apac|asia)\b", re.I)),
]


def parse_location(location: str, country_hint: str = "", remote_hint: Optional[bool] = None, workplace: str = "") -> dict:
    loc = (location or "").strip()
    low = loc.lower()
    country, region = "", ""
    hint = (country_hint or "").strip().lower()
    if hint and hint in COUNTRIES:
        country, region = COUNTRIES[hint]
    if not country:
        # longest alias first so "new york" beats "york"-like partials
        tokens = [t.strip() for t in re.split(r"[,/;|()\-–]| or | and ", low) if t.strip()]
        for tok in tokens:
            tok = re.sub(r"\b(remote|hybrid|onsite|on-site|in office|office|hq|greater|area|metropolitan)\b", "", tok).strip()
            if tok in COUNTRIES:
                country, region = COUNTRIES[tok]
                break
        if not country:
            for alias in sorted(COUNTRIES, key=len, reverse=True):
                if len(alias) >= 4 and re.search(rf"\b{re.escape(alias)}\b", low):
                    country, region = COUNTRIES[alias]
                    break
        if not country and _US_STATE.search(loc):
            country, region = "United States", "north_america"

    wp = (workplace or "").lower().replace("_", "").replace("-", "").replace(" ", "")
    # an explicit workplace type from the ATS wins over looser hints
    if "hybrid" in wp or (not wp and _HYBRID.search(loc)):
        mode = "hybrid"
    elif "remote" in wp or (not wp and (remote_hint or _REMOTE.search(loc))):
        mode = "remote"
    elif wp == "onsite" or (loc and country):
        mode = "onsite"
    else:
        mode = "unknown"

    scope = ""
    if mode == "remote":
        if _WORLDWIDE.search(loc):
            scope = "Worldwide"
        elif country:
            scope = country
        else:
            for name, pat in _REGION_SCOPES:
                if pat.search(loc):
                    scope = name
                    break
    return {"country": country, "region": region, "remote_mode": mode, "remote_scope": scope}


# ---------------------------------------------------------------- salary

_CUR = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "usd": "USD", "eur": "EUR", "gbp": "GBP", "cad": "CAD",
        "chf": "CHF", "aed": "AED", "sgd": "SGD", "pln": "PLN", "jpy": "JPY", "sek": "SEK", "dkk": "DKK", "aud": "AUD"}
_SALARY = re.compile(
    r"(?P<c1>[$€£¥]|USD|EUR|GBP|CAD|CHF|AED|SGD|PLN|JPY|SEK|DKK|AUD)\s?(?P<a>\d{1,3}(?:[,.\s]\d{3})+|\d{2,3}\s?[kK])"
    r"(?:\s?(?:-|–|—|to)\s?(?:[$€£¥]|USD|EUR|GBP|CAD|CHF)?\s?(?P<b>\d{1,3}(?:[,.\s]\d{3})+|\d{2,3}\s?[kK]))?",
)


def _num(s: str) -> float:
    s = s.strip()
    if s.lower().endswith("k"):
        return float(re.sub(r"[^\d.]", "", s[:-1])) * 1000
    return float(re.sub(r"[^\d]", "", s))


def extract_salary(text: str) -> dict:
    """Find an explicitly stated pay range. Returns {} when none is stated (never guessed)."""
    for m in _SALARY.finditer(text or ""):
        try:
            a = _num(m.group("a"))
            b = _num(m.group("b")) if m.group("b") else None
        except ValueError:
            continue
        if a < 10000 and (b is None or b < 10000):
            continue  # too small to be an annual salary; likely a bonus/stipend/number
        cur = _CUR.get(m.group("c1").lower(), m.group("c1").upper())
        ctx = (text[max(0, m.start() - 60): m.end() + 40]).lower()
        if not re.search(r"salary|compensation|pay|base|range|per year|annual|annually|/year|/yr|ote|gross", ctx):
            continue
        return {"text": m.group(0).strip(), "min": a, "max": b or a, "currency": cur}
    return {}


# ---------------------------------------------------------------- "what you'll do"

_DO_HEAD = re.compile(
    r"what you(?:'|’| wi)ll (?:do|be doing|work on)|what you will (?:do|be doing)|responsibilit|your (?:role|mission|impact|day|tasks)|"
    r"in this role|the role|about the (?:role|job|position)|you will\b|what you'll own|key duties|the opportunity|the job",
    re.I,
)


def summarize_role(description_html: str, description_text: str, limit: int = 230) -> str:
    """Deterministic one-liner: first bullets under the responsibilities heading, else opening sentences."""
    raw = description_html or ""
    if "&lt;" in raw and "<" not in raw:
        raw = html_lib.unescape(raw)
    bullets: list[str] = []
    if raw:
        soup = BeautifulSoup(raw, "html.parser")
        for head in soup.find_all(["h1", "h2", "h3", "h4", "strong", "b", "p"]):
            txt = head.get_text(" ", strip=True)
            if 0 < len(txt) < 90 and _DO_HEAD.search(txt):
                ul = head.find_next(["ul", "ol"])
                if ul:
                    bullets = [li.get_text(" ", strip=True) for li in ul.find_all("li")][:3]
                    if bullets:
                        break
    if not bullets:
        # plain-text fallback: a responsibilities heading followed by "- " bullet lines
        lines = (description_text or "").split("\n")
        for i, line in enumerate(lines):
            if 0 < len(line) < 90 and _DO_HEAD.search(line) and not line.lstrip().startswith("-"):
                got = []
                for nxt in lines[i + 1: i + 12]:
                    if nxt.lstrip().startswith("-"):
                        got.append(nxt.lstrip(" -"))
                    elif got:
                        break
                if got:
                    bullets = got[:3]
                    break
    if bullets:
        out = "; ".join(b.rstrip(".;") for b in bullets if b)
    else:
        sents = [s for s in sentences(description_text or "") if len(s) > 40]
        out = " ".join(sents[:2])
    out = re.sub(r"\s+", " ", out).strip()
    if len(out) > limit:
        out = out[: limit - 1].rsplit(" ", 1)[0] + "…"
    return out
