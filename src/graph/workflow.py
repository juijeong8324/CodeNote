import logging

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.code_reviewer import code_reviewer_node
from src.agents.analyzer import analyzer_node
from src.agents.markdown_writer import markdown_writer_node
from src.graph.state import CodeNoteState

logger = logging.getLogger(__name__)


def _route(state: CodeNoteState, next_node: str) -> str:
    """에러가 있으면 END로, 없으면 next_node로 라우팅."""
    if state.get("error"):
        logger.error("워크플로우 중단 — %s", state["error"])
        return END
    return next_node


def build_workflow() -> CompiledStateGraph:
    workflow = StateGraph(CodeNoteState)

    workflow.add_node("code_reviewer", code_reviewer_node)
    workflow.add_node("analyzer", analyzer_node)
    workflow.add_node("markdown_writer", markdown_writer_node)

    workflow.set_entry_point("code_reviewer")

    workflow.add_conditional_edges(
        "code_reviewer",
        lambda s: _route(s, "analyzer"),
    )
    workflow.add_conditional_edges(
        "analyzer",
        lambda s: _route(s, "markdown_writer"),
    )
    workflow.add_conditional_edges(
        "markdown_writer",
        lambda s: _route(s, END),
    )

    return workflow.compile()


codenote_workflow: CompiledStateGraph = build_workflow()
