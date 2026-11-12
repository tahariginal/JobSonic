import pytest

from app.normalize import (extract_salary, extract_years, fingerprint, html_to_text, is_relevant_title, parse_location,
                           role_family, summarize_role, title_level)


@pytest.mark.parametrize("title,ok", [
    ("Software Engineer", True), ("Junior Backend Developer", True), ("Graduate Software Engineer 2027", True),
    ("AI Agent Engineer", True), ("Sales Engineer", False), ("Engineering Manager", False), ("Account Executive", False),
    ("Hardware Engineer", False), ("Solutions Engineer", False), ("Product Designer", False), ("Mobile Engineer (iOS)", True),
])
def test_title_relevance(title, ok):
    assert is_relevant_title(title) is ok


def test_title_keyword_overrides():
    assert is_relevant_title("Forward Deployed Specialist", extra=["forward deployed"])
    assert not is_relevant_title("Software Engineer, Ads", exclude=["ads"])


@pytest.mark.parametrize("title,level", [
    ("Senior Software Engineer", "senior"), ("Staff Engineer", "senior"), ("Software Engineer II", "mid"),
    ("Junior Developer", "junior"), ("Graduate Software Engineer", "junior"), ("Software Engineer, New Grad", "junior"),
    ("Software Engineering Intern", "intern"), ("Backend Engineer", "unknown"), ("Lead Mobile Engineer", "senior"),
])
def test_title_level(title, level):
    assert title_level(title) == level


@pytest.mark.parametrize("title,fam", [
    ("Applied AI Engineer", "applied_ai"), ("Backend Engineer", "backend"), ("Full-Stack Developer", "fullstack"),
    ("iOS Engineer", "mobile"), ("Platform Engineer", "platform"), ("Automation Engineer", "automation"), ("Software Engineer", "software"),
])
def test_role_family(title, fam):
    assert role_family(title) == fam


@pytest.mark.parametrize("text,years", [
    ("You have 5+ years of professional experience building APIs.", 5),
    ("0-2 years of experience in software development", 2) ,
    ("At least three years of industry experience.", 3),
    ("We have been in business for 20 years.", None),
    ("1+ years experience with Python. 4+ years of experience with distributed systems.", 4),
    ("No prior experience required.", None),
])
def test_extract_years(text, years):
    got, quote = extract_years(text)
    if years == 2:
        assert got == 0  # the minimum of the range is what matters
    else:
        assert got == years
    if got is not None:
        assert quote


def test_years_range_uses_minimum():
    got, _ = extract_years("2-4 years of professional experience")
    assert got == 2


@pytest.mark.parametrize("loc,country,mode", [
    ("Berlin, Germany", "Germany", "onsite"), ("London", "United Kingdom", "onsite"), ("Remote - US", "United States", "remote"),
    ("San Francisco, CA", "United States", "onsite"), ("Tokyo, Japan (Hybrid)", "Japan", "hybrid"), ("Dubai", "United Arab Emirates", "onsite"),
    ("Remote (Worldwide)", "", "remote"), ("Casablanca, Morocco", "Morocco", "onsite"),
])
def test_parse_location(loc, country, mode):
    out = parse_location(loc)
    assert out["country"] == country and out["remote_mode"] == mode


def test_remote_scope_and_workplace_priority():
    assert parse_location("Remote (Worldwide)")["remote_scope"] == "Worldwide"
    assert parse_location("Remote, EMEA")["remote_scope"] == "EMEA"
    # explicit workplace type beats an "isRemote" style hint
    assert parse_location("Paris", remote_hint=True, workplace="Hybrid")["remote_mode"] == "hybrid"


def test_salary_only_when_stated():
    s = extract_salary("The base salary range for this role is $120,000 - $150,000 per year.")
    assert s["min"] == 120000 and s["max"] == 150000 and s["currency"] == "USD"
    assert extract_salary("Annual salary: €55k–€70k gross")["min"] == 55000
    assert extract_salary("We raised $40,000,000 in funding.") == {}
    assert extract_salary("Competitive salary and equity.") == {}


def test_summary_and_text():
    html = "<p>About us blah.</p><h3>What you'll do</h3><ul><li>Build APIs</li><li>Ship features</li><li>Write tests</li><li>More</li></ul>"
    assert summarize_role(html, html_to_text(html)) == "Build APIs; Ship features; Write tests"
    assert "- Build APIs" in html_to_text(html)
    assert html_to_text("&lt;p&gt;Hello&lt;/p&gt;") == "Hello"


def test_fingerprint_stable():
    assert fingerprint("A", "b  c") == fingerprint("a", "B c")
    assert fingerprint("A", "b") != fingerprint("A", "c")


@pytest.mark.parametrize("title,level", [("Software Engineer 3 - Enterprise Architecture", "senior"), ("Software Engineer 2", "mid"),
                                         ("Software Engineer 1", "junior"), ("Software Engineer, Level 4", "senior"), ("Backend Engineer - 2027 Start", "unknown")])
def test_numeric_ladder_levels(title, level):
    assert title_level(title) == level
