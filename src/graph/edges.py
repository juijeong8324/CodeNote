import logging

from langgraph.graph import END

from src.graph.state import CodeNoteState

logger = logging.getLogger(__name__)


def route_or_end(next_node: str):
    """에러가 있으면 END로, 없으면 next_node로 라우팅."""
    def _route(state: CodeNoteState) -> str:
        if state.get("error"):
            logger.error("워크플로우 중단 — %s", state["error"])
            return END
        return next_node
    return _route
