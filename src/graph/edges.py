import logging

from langgraph.types import Send

from src.graph.state import CodeNoteState, ProblemAnalysis

logger = logging.getLogger(__name__)


def fan_out_to_analyzers(state: CodeNoteState):
    return [
        Send("code_analyzer", ProblemAnalysis(
            folder=p["folder"],
            file_urls=p["file_urls"],
            files=None,
            analysis=None,
            error=None,
        ))
        for p in state["problems"]
    ]


def chain_to_doc_writer(state: dict):
    analyzed = state.get("analyzed", [])
    if not analyzed or analyzed[0].get("error"):
        return []
    return [Send("doc_writer", analyzed[0])]
