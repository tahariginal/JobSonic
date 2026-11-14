"""Pydantic schemas. The profile is user-verified data: nothing here is ever inferred."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Personal(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    city: str = ""
    country: str = ""
    citizenship: str = ""
    headline: str = ""
    summary: str = ""


class Links(BaseModel):
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    other: list[str] = Field(default_factory=list)


class Education(BaseModel):
    school: str = ""
    program: str = ""
    credential: str = ""  # exactly as the candidate describes it; never "Bachelor" unless they say so
    start: str = ""
    end: str = ""
    notes: str = ""


class Experience(BaseModel):
    company: str = ""
    title: str = ""
    kind: str = ""  # internship | full-time | freelance ...
    start: str = ""
    end: str = ""
    location: str = ""
    description: str = ""


class Project(BaseModel):
    name: str = ""
    description: str = ""
    url: str = ""
    tech: list[str] = Field(default_factory=list)
    status: str = ""  # e.g. "in progress", "shipped" - as stated by the candidate


class Language(BaseModel):
    language: str = ""
    level: str = ""


class WorkAuthorization(BaseModel):
    authorized_countries: list[str] = Field(default_factory=list)
    needs_sponsorship_elsewhere: bool = True
    notes: str = ""


class Preferences(BaseModel):
    target_roles: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    open_to_relocation: bool = True
    open_to_remote: bool = True
    salary_min: Optional[float] = None
    salary_currency: str = ""
    earliest_start_date: str = ""
    motivation_answer: str = (
        "I'm looking for a role where I can contribute to useful work, keep learning, and be part of a team I can learn from. "
        "I enjoy solving problems, turning ideas into something practical, and improving things through feedback. "
        "I'd like to bring that approach to this role, take responsibility for my work, and grow with the team over time."
    )
    max_years_experience: float = 2


class StandardAnswer(BaseModel):
    question: str = ""
    answer: str = ""


class ProfileData(BaseModel):
    personal: Personal = Field(default_factory=Personal)
    links: Links = Field(default_factory=Links)
    email_accounts: list[str] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    work_authorization: WorkAuthorization = Field(default_factory=WorkAuthorization)
    preferences: Preferences = Field(default_factory=Preferences)
    standard_answers: list[StandardAnswer] = Field(default_factory=list)


def seed_profile() -> ProfileData:
    """Initial profile built only from facts the candidate stated in the project brief."""
    return ProfileData(
        personal=Personal(
            country="Morocco",
            citizenship="Moroccan",
            headline="Software engineering student at 1337 School (42 Network)",
        ),
        links=Links(github="https://github.com/tahariginal", portfolio="https://tkoulal.tech"),
        education=[
            Education(
                school="1337 School (42 Network)",
                program="Software engineering, project-based curriculum",
                credential="42 Common Core (completed)",
                notes="Project-based engineering education; not a conventional bachelor's degree.",
            )
        ],
        experience=[
            Experience(company="PHOVA Technology", title="Software Engineering Intern", kind="internship"),
            Experience(company="UM6P IDC", title="VR Development Intern", kind="internship"),
        ],
        projects=[
            Project(
                name="Mobile Factory",
                description="AI-driven mobile application workflow system.",
                status="in progress",
            )
        ],
        skills=["C", "C++", "Backend development", "APIs", "Software systems", "Automation"],
        interests=[
            "Applied AI",
            "AI agents",
            "MCP",
            "RAG",
            "Tool calling",
            "Orchestration",
            "Backend engineering",
            "Full-stack development",
            "Mobile applications",
            "Product engineering",
        ],
        work_authorization=WorkAuthorization(
            authorized_countries=["Morocco"],
            needs_sponsorship_elsewhere=True,
            notes="Moroccan citizen based in Morocco. No US, UK, EU or other foreign work authorization. "
            "Needs employer-supported work authorization for international on-site employment.",
        ),
        preferences=Preferences(
            target_roles=[
                "Software Engineer",
                "Backend Engineer",
                "Full-Stack Engineer",
                "Applied AI Engineer",
                "AI Agent Engineer",
                "Automation Engineer",
                "API Integration Engineer",
                "Platform Engineer",
                "Mobile Engineer",
                "Graduate Software Engineer",
                "Junior Developer",
                "Entry-Level Software Engineer",
            ],
            open_to_relocation=True,
            open_to_remote=True,
            max_years_experience=2,
        ),
    )


def profile_gaps(p: ProfileData) -> list[str]:
    """What still has to be filled in before forms can be completed truthfully."""
    gaps = []
    if not p.personal.first_name or not p.personal.last_name:
        gaps.append("Full name")
    if not p.personal.email:
        gaps.append("Contact email")
    if not p.personal.phone:
        gaps.append("Phone number")
    if not p.links.linkedin:
        gaps.append("LinkedIn URL (optional but commonly requested)")
    if not p.languages:
        gaps.append("Languages and levels (language requirements cannot be checked until confirmed)")
    if not p.preferences.earliest_start_date:
        gaps.append("Earliest available start date")
    return gaps
