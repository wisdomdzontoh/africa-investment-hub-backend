"""Enumerations shared across models and schemas (PRD §10).

Each is a ``str``-backed Enum so values serialise cleanly to JSON and persist
as native PostgreSQL enum types. ``values_callable`` is used at column
definition so the *value* (not the Python name) is stored.
"""

from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    investor = "investor"
    project_owner = "project_owner"
    admin = "admin"


class UserStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    suspended = "suspended"


class Locale(str, enum.Enum):
    en = "en"
    fr = "fr"
    zh = "zh"


class RiskLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class ProjectStage(str, enum.Enum):
    concept = "concept"
    pre_revenue = "pre_revenue"
    revenue_generating = "revenue_generating"
    expansion = "expansion"


class FundingType(str, enum.Enum):
    equity = "equity"
    debt = "debt"
    jv = "jv"
    ppp = "ppp"
    acquisition = "acquisition"


class ProjectStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    suspended = "suspended"


class MatchSource(str, enum.Enum):
    ai_generated = "ai_generated"
    admin_manual = "admin_manual"


class MatchStatus(str, enum.Enum):
    """Match pipeline (PRD §10 / §6.10). Ordering matters for the NDA gate:
    full project details unlock only at ``nda_signed`` or later."""

    ai_recommended = "ai_recommended"
    admin_reviewed = "admin_reviewed"
    investor_notified = "investor_notified"
    investor_interested = "investor_interested"
    nda_sent = "nda_sent"
    nda_signed = "nda_signed"
    confidential = "confidential"
    mou_drafted = "mou_drafted"
    mou_signed = "mou_signed"
    in_negotiation = "in_negotiation"
    due_diligence = "due_diligence"
    closed_won = "closed_won"
    closed_lost = "closed_lost"
    dismissed = "dismissed"


# Pipeline ordering used to evaluate the NDA gate. Statuses at or beyond
# ``nda_signed`` unlock privileged information. Terminal/branch statuses
# (confidential, dismissed, closed_*) are handled explicitly in the gate.
MATCH_PIPELINE_ORDER: dict[MatchStatus, int] = {
    MatchStatus.ai_recommended: 0,
    MatchStatus.admin_reviewed: 1,
    MatchStatus.investor_notified: 2,
    MatchStatus.investor_interested: 3,
    MatchStatus.nda_sent: 4,
    MatchStatus.nda_signed: 5,
    MatchStatus.mou_drafted: 6,
    MatchStatus.mou_signed: 7,
    MatchStatus.in_negotiation: 8,
    MatchStatus.due_diligence: 9,
    MatchStatus.closed_won: 10,
}

# Statuses at which a project's ``full_description`` and deal-room documents
# are unlocked for the matched investor.
NDA_UNLOCKED_STATUSES: frozenset[MatchStatus] = frozenset(
    {
        MatchStatus.nda_signed,
        MatchStatus.mou_drafted,
        MatchStatus.mou_signed,
        MatchStatus.in_negotiation,
        MatchStatus.due_diligence,
        MatchStatus.closed_won,
    }
)


class ConsultantStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    suspended = "suspended"


class ContactPreference(str, enum.Enum):
    email = "email"
    platform_message = "platform_message"


class ConsultantMatchStatus(str, enum.Enum):
    recommended = "recommended"
    viewed = "viewed"
    contacted = "contacted"
    engaged = "engaged"
    dismissed = "dismissed"


class DueDiligenceStatus(str, enum.Enum):
    requested = "requested"
    in_progress = "in_progress"
    completed = "completed"


class MilestoneStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    overdue = "overdue"


class KnowledgeContentType(str, enum.Enum):
    country = "country"
    faq = "faq"
    sector_guide = "sector_guide"
    project_summary = "project_summary"
    platform_doc = "platform_doc"
