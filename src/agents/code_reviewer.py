import logging

from langchain_anthropic import ChatAnthropic
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent

from src.graph.state import CodeNoteState
from src.mcp.config import github_mcp_config
from src.utils.retry import agent_retry

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 GitHub에서 코드를 읽어 원시 정보를 추출하는 코드 리뷰어입니다.

다음 두 가지를 추출하세요:

[코드 원문]
- 파일 전체 내용을 그대로 가져오세요.

[주석 분석]
- 코드에 있는 모든 주석을 추출하세요.
- 주석이 없다면 "주석 없음" 이라고 작성하세요.
- 주석을 보고 작성자가 어떤 의도로 코드를 작성했는지 파악하세요.

반드시 아래 형식으로 출력하세요:

===CODE===
(코드 원문)
===COMMENTS===
(추출한 주석 및 의도 분석)"""


@agent_retry(max_attempts=3)
async def _invoke(agent, github_url: str) -> str:
    result = await agent.ainvoke({
        "messages": [("user", f"다음 GitHub URL의 파일을 읽고 정보를 추출해주세요: {github_url}")]
    })
    return result["messages"][-1].content


def _parse_output(raw: str) -> tuple[str, str]:
    """에이전트 출력에서 코드와 주석을 분리합니다."""
    code, comments = "", ""
    if "===CODE===" in raw and "===COMMENTS===" in raw:
        parts = raw.split("===COMMENTS===")
        code = parts[0].replace("===CODE===", "").strip()
        comments = parts[1].strip()
    else:
        code = raw  # 파싱 실패 시 전체를 코드로 저장
    return code, comments


async def code_reviewer_node(state: CodeNoteState) -> CodeNoteState:
    logger.info("Code Reviewer 시작: %s", state["github_url"])
    try:
        async with MultiServerMCPClient({"github": github_mcp_config()}) as client:
            tools = client.get_tools()
            llm = ChatAnthropic(model="claude-opus-4-6")
            agent = create_react_agent(llm, tools, state_modifier=SYSTEM_PROMPT)
            raw_output = await _invoke(agent, state["github_url"])

        raw_code, comments = _parse_output(raw_output)
        logger.info("Code Reviewer 완료 — 코드 %d자, 주석 %d자", len(raw_code), len(comments))
        return {**state, "raw_code": raw_code, "comments": comments, "error": None}

    except Exception as e:
        logger.error("Code Reviewer 실패: %s", e)
        return {**state, "error": f"[CodeReviewer] {e}"}
