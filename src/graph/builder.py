from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.graph.edges import route_or_end
from src.graph.nodes import analyzer_node, code_reviewer_node, markdown_writer_node
from src.graph.state import CodeNoteState


def build_graph() -> CompiledStateGraph:
    graph = StateGraph(CodeNoteState)

    graph.add_node("code_reviewer", code_reviewer_node)
    graph.add_node("analyzer", analyzer_node)
    graph.add_node("markdown_writer", markdown_writer_node)

    graph.set_entry_point("code_reviewer")

    graph.add_conditional_edges("code_reviewer", route_or_end("analyzer"))
    graph.add_conditional_edges("analyzer", route_or_end("markdown_writer"))
    graph.add_conditional_edges("markdown_writer", route_or_end(END))

    return graph.compile()


codenote_graph: CompiledStateGraph = build_graph()
