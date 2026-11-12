from datetime import datetime

import pytest

from app import analysis
from app.schemas import Language, seed_profile

NOW = datetime(2026, 11, 1)


def visa(desc, country="Germany", mode="onsite", scope="", loc="Berlin, Germany", profile=None):
    return analysis.analyze_visa(desc, country=country, remote_mode=mode, remote_scope=scope, location_raw=loc,
                                 source_url="https://x/job", profile=profile or seed_profile(), now=NOW)


@pytest.mark.parametrize("text,status", [
    ("We offer visa sponsorship and relocation support for this role.", "confirmed"),
    ("Visa sponsorship is available for candidates outside the EU.", "confirmed"),
    ("We will support you with your visa and work permit.", "confirmed"),
    ("Sponsorship may be available for exceptional candidates.", "conditional"),
    ("Visa sponsorship is considered on a case-by-case basis.", "conditional"),
    ("We are unable to sponsor visas for this position.", "not_supported"),
    ("Applicants must be authorised to work in the U.K.", "not_supported"),
    ("You must have the right to work in Germany without sponsorship.", "not_supported"),
    ("We do not offer visa sponsorship at this time.", "not_supported"),
    ("Great team, great snacks.", "unverified"),
])
def test_visa_classification(text, status):
    out = visa(text)
    assert out["visa_status"] == status
    ev = out["visa_evidence"][0]
    assert ev["source_url"] == "https://x/job" and ev["checked_at"].startswith("2026-11-01")
    if status != "unverified":
        assert ev["quote"] and ev["quote"] in text and ev["kind"] == "verified"
    else:
        assert ev["quote"] == "" and ev["kind"] == "unverified"


def test_relocation_alone_does_not_prove_visa():
    out = visa("We provide a generous relocation package for new joiners.")
    assert out["visa_status"] == "unverified"
    assert out["relocation"] == "yes" and out["relocation_evidence"][0]["quote"]


def test_negative_statement_wins_over_positive():
    out = visa("We offer visa sponsorship in some offices. For this role we are unable to sponsor visas.")
    assert out["visa_status"] == "not_supported"


def test_morocco_needs_no_sponsorship():
    assert visa("Join us.", country="Morocco", loc="Casablanca, Morocco")["visa_status"] == "not_required"


def test_remote_worldwide_is_only_likely_and_remote_us_is_no():
    w = visa("Work from anywhere in the world.", country="", mode="remote", scope="Worldwide", loc="Remote (Worldwide)")
    assert w["remote_from_morocco"] == "likely"
    us = visa("Remote role.", country="United States", mode="remote", scope="United States", loc="Remote - US")
    assert us["remote_from_morocco"] == "no"
    emea = visa("Remote role.", country="", mode="remote", scope="EMEA", loc="Remote, EMEA")
    assert emea["remote_from_morocco"] == "unverified"


def elig(title, desc, profile=None, country="Germany", active=True, **vk):
    p = profile or seed_profile()
    v = visa(desc, country=country, profile=p, **vk)
    return analysis.analyze_eligibility(title=title, description=desc, employment_type="", visa=v, profile=p,
                                        source_url="https://x/job", is_active=active)


def codes(out, sev):
    return {r["code"] for r in out["eligibility_reasons"] if r["severity"] == sev}


def test_senior_and_years_rejected():
    assert elig("Senior Backend Engineer", "Visa sponsorship is available.")["eligibility"] == "rejected"
    out = elig("Backend Engineer", "5+ years of professional experience. Visa sponsorship is available.")
    assert out["eligibility"] == "rejected" and "years" in codes(out, "reject")
    assert out["eligibility_reasons"][0]["quote"]


def test_borderline_goes_to_needs_review_not_eligible():
    out = elig("Backend Engineer", "3+ years of experience with Python. Visa sponsorship is available.")
    assert out["eligibility"] == "needs_review" and "years_borderline" in codes(out, "review")
    out = elig("Backend Engineer", "Build things. Visa sponsorship is available.")
    assert out["eligibility"] == "needs_review" and "level_unknown" in codes(out, "review")
    assert [r for r in out["eligibility_reasons"] if r["code"] == "level_unknown"][0]["kind"] == "unverified"


def test_junior_with_sponsorship_is_eligible():
    out = elig("Junior Backend Engineer", "0-2 years of experience. Visa sponsorship is available.")
    assert out["eligibility"] == "eligible" and out["experience_level"] == "junior"


def test_degree_is_never_assumed_equivalent():
    out = elig("Junior Software Engineer", "Bachelor's degree in Computer Science required. Visa sponsorship is available.")
    assert out["eligibility"] == "needs_review" and "degree" in codes(out, "review")
    assert "not assumed" in [r for r in out["eligibility_reasons"] if r["code"] == "degree"][0]["text"]
    out = elig("Junior Software Engineer", "Bachelor's degree in Computer Science or equivalent practical experience. Visa sponsorship is available.")
    assert out["eligibility"] == "eligible" and "degree_alt" in codes(out, "ok")
    out = elig("Junior Software Engineer", "A PhD is required for this role.")
    assert out["eligibility"] == "rejected"


def test_unconfirmed_language_flagged_confirmed_language_passes():
    desc = "Fluent German is required. Visa sponsorship is available."
    assert "language" in codes(elig("Junior Developer", desc), "review")
    p = seed_profile()
    p.languages = [Language(language="German", level="C1")]
    assert "language" not in codes(elig("Junior Developer", desc, profile=p), "review")
    soft = elig("Junior Developer", "German is a plus. Visa sponsorship is available.")
    assert "language" not in codes(soft, "review")


def test_no_sponsorship_unpaid_closed_rejected():
    assert "no_sponsorship" in codes(elig("Junior Developer", "We are unable to sponsor visas."), "reject")
    assert "unpaid" in codes(elig("Junior Developer", "This is an unpaid position."), "reject")
    assert "closed" in codes(elig("Junior Developer", "Visa sponsorship is available.", active=False), "reject")


def test_internship_needs_review():
    out = elig("Software Engineering Intern", "Join us. Visa sponsorship is available.")
    assert out["eligibility"] == "needs_review" and "internship" in codes(out, "review")


def fit(title, desc, **kw):
    p = kw.pop("profile", None) or seed_profile()
    v = visa(desc, profile=p, **{k: kw.pop(k) for k in ("country", "mode", "scope", "loc") if k in kw})
    e = analysis.analyze_eligibility(title=title, description=desc, employment_type="", visa=v, profile=p, source_url="u")
    from app.normalize import role_family
    return analysis.score_fit(title=title, description=desc, role_family=role_family(title), level=e["experience_level"],
                              min_years=e["min_years"], eligibility=e["eligibility"], visa=v, country="Germany", region="europe",
                              remote_mode="onsite", salary_min=None, salary_currency="", profile=p)


def test_fit_is_explainable_and_ordered():
    strong = fit("Junior Backend Engineer", "0-2 years of experience. Build APIs in C++ and backend automation with RAG and MCP. Visa sponsorship is available.")
    weak = fit("Backend Engineer", "4 years of experience with Ruby on Rails and Kafka. We are unable to sponsor visas.")
    assert strong["fit_stars"] == 5 and weak["fit_stars"] == 1
    assert strong["fit_score"] > weak["fit_score"]
    assert "visa support explicitly mentioned" in strong["fit_reason"]
    assert "c++" in strong["fit_breakdown"]["matched_skills"]
    assert set(strong["fit_breakdown"]["components"]) == {"skills", "interest", "level", "visa", "location", "salary"}


def test_rejected_jobs_are_one_star():
    out = fit("Senior Backend Engineer", "Build APIs in C++. Visa sponsorship is available.")
    assert out["fit_stars"] == 1


# ---- regression cases taken from real postings found during the first production search ----
@pytest.mark.parametrize("text,status", [
    ("Kindly note that relocation or visa support is not offered for this role.", "not_supported"),
    ("Your actual level and base salary will be determined on a case-by-case basis and may vary based on experience.", "unverified"),
    ("Grow our role-based access model so access is granted by role rather than case by case.", "unverified"),
    ("You must be able to access technology subject to export laws without sponsorship for an export license.", "unverified"),
    ("OKX will be prioritising applicants who have a current right to work in Hong Kong, and do not require OKX's sponsorship of a visa.", "conditional"),
    ("For selected candidates, Catawiki can provide visa sponsorship and relocation support to the relevant location, subject to eligibility.", "conditional"),
    ("Visa sponsorship: We do sponsor visas!", "confirmed"),
    ("You can count on the visa support from our talent support team, a relocation package and free language classes.", "confirmed"),
    ("Unfortunately, we are unable to provide visa sponsorship or support visa applications for this role.", "not_supported"),
    ("To be eligible, candidates must be authorized to work in Canada; visa sponsorship is not available for this role.", "not_supported"),
    ("We proudly sponsor the local Python meetup and our engineers speak at conferences.", "unverified"),
    ("Active US Security Clearance at or above the Secret level.", "unverified"),
])
def test_visa_real_world_regressions(text, status):
    assert visa(text)["visa_status"] == status


def test_security_clearance_is_an_eligibility_rule_not_a_visa_claim():
    out = elig("Junior Software Engineer", "Active US Security Clearance at or above the Secret level. Visa sponsorship is available.")
    assert out["eligibility"] == "rejected" and "clearance" in codes(out, "reject")
    soft = elig("Junior Software Engineer", "A security clearance is not required for this role. Visa sponsorship is available.")
    assert soft["eligibility"] != "rejected"


def test_unverified_sponsorship_caps_the_rating():
    out = fit("Junior Backend Engineer", "0-2 years of experience. Build APIs in C++ and backend automation with RAG and MCP.")
    assert out["fit_stars"] == 4


def test_remote_anywhere_sentence_is_found_without_visa_wording():
    out = visa("We are remote-first and you can work from anywhere in the world.", country="", mode="remote", scope="", loc="Remote")
    assert out["remote_from_morocco"] == "likely"


def test_degree_or_equivalent_combination_counts_as_alternative():
    out = elig("Junior Software Engineer", "Minimum education: Bachelor's degree or an equivalent combination of education, training, and/or experience. Visa sponsorship is available.")
    assert "degree_alt" in codes(out, "ok") and "degree" not in codes(out, "review")
