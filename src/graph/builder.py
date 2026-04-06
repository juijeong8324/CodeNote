from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.graph.edges import chain_to_doc_writer, fan_out_to_analyzers
from src.graph.nodes import (
    code_analyzer_node,
    coordinator_node,
    doc_writer_node,
    github_publisher_node,
    supervisor_node,
)
from src.graph.state import CodeNoteState


def build_graph() -> CompiledStateGraph:
    graph = StateGraph(CodeNoteState)

    # Nodes
    graph.add_node("coordinator", coordinator_node)        # 파일 → 문제 그룹핑
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("code_analyzer", code_analyzer_node)   # MAP: 문제별 분석
    graph.add_node("doc_writer", doc_writer_node)          # MAP: 노트 작성
    graph.add_node("github_publisher", github_publisher_node)  # REDUCE: 한번에 push

    # Edges
    graph.set_entry_point("coordinator")
    graph.add_edge("coordinator", "supervisor")
    graph.add_conditional_edges("supervisor", fan_out_to_analyzers, ["code_analyzer"])  # fan-out
    graph.add_conditional_edges("code_analyzer", chain_to_doc_writer, ["doc_writer"])   # 
    graph.add_edge("doc_writer", "github_publisher")                                    # join (모두 완료 후 1회)
    graph.add_edge("github_publisher", END)

    return graph.compile()


codenote_graph: CompiledStateGraph = build_graph()


if __name__ == "__main__":
    png = codenote_graph.get_graph(xray=True).draw_mermaid_png()
    with open("graph.png", "wb") as f:
        f.write(png)
    print("graph.png 저장됨")
