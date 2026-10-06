import logging

from powereditor.decide.base import DecisionEngine
from powereditor.decide.heuristic import HeuristicEngine
from powereditor.settings_store import UserSettings

logger = logging.getLogger(__name__)


def create_engine(settings: UserSettings) -> DecisionEngine:
    """The configured engine; model-backed engines arrive in Phase 4, until then heuristic."""
    if settings.decision_engine != "heuristic":
        logger.warning(
            "Decision engine %r is not available yet; using the heuristic engine",
            settings.decision_engine,
        )
    return HeuristicEngine(settings.take_weights, settings.language)
