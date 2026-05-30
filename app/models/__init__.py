"""SQLAlchemy models. Importing this package registers every model on
``Base.metadata`` so Alembic autogenerate and ``create_all`` see them all.
"""

from app.models.audit import AuditLog
from app.models.chat import ChatSession
from app.models.consultant import ConsultantMatch, ConsultantProfile
from app.models.country import CountryContent, CountryContentVersion
from app.models.due_diligence import DueDiligenceRequest
from app.models.homepage import HomepageContent
from app.models.investor import InvestorProfile
from app.models.knowledge import KnowledgeChunk
from app.models.match import Match
from app.models.milestone import Milestone
from app.models.notification import Notification
from app.models.project import Project
from app.models.user import User

__all__ = [
    "AuditLog",
    "ChatSession",
    "ConsultantMatch",
    "ConsultantProfile",
    "CountryContent",
    "CountryContentVersion",
    "DueDiligenceRequest",
    "HomepageContent",
    "InvestorProfile",
    "KnowledgeChunk",
    "Match",
    "Milestone",
    "Notification",
    "Project",
    "User",
]
