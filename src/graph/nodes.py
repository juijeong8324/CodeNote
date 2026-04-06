import logging
from pathlib import Path

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent

from src.graph.state import CodeNoteState
from src.mcp.config import github_mcp_config, notion_mcp_config
from src.utils.retry import agent_retry

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


# prompts

def load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


_CODE_REVIEWER_PROMPT = load_prompt("code_reviewer")
_ANALYZER_PROMPT = load_prompt("analyzer")
_MARKDOWN_WRITER_PROMPT = load_prompt("markdown_writer")
_NOTION_UPLOAD_PROMPT = load_prompt("notion_upload")


# helpers

def _parse_code_review(raw: str) -> tuple[str, str]:
    code, comments = "", ""
    if "===CODE===" in raw and "===COMMENTS===" in raw:
        parts = raw.split("===COMMENTS===")
        code = parts[0].replace("===CODE===", "").strip()
        comments = parts[1].strip()
    else:
        code = raw
    return code, comments


def _extract_title(github_url: str) -> str:
    filename = github_url.rstrip("/").split("/")[-1]
    title = filename.rsplit(".", 1)[0] if "." in filename else filename
    return title.replace("_", " ").replace("-", " ")


# nodes

@agent_retry(max_attempts=3)
async def _invoke_agent(agent, message: str) -> str:
    result = await agent.ainvoke({"messages": [("user", message)]})
    return result["messages"][-1].content


@agent_retry(max_attempts=3)
async def _invoke_llm(llm, messages) -> str:
    response = await llm.ainvoke(messages)
    return response.content


async def code_reviewer_node(state: CodeNoteState) -> CodeNoteState:
    logger.info("Code Reviewer 시작: %s", state["github_url"])
    try:
        async with MultiServerMCPClient({"github": github_mcp_config()}) as client:
            tools = client.get_tools()
            llm = ChatAnthropic(model="claude-opus-4-6")
            agent = create_react_agent(llm, tools, state_modifier=_CODE_REVIEWER_PROMPT)
            raw = await _invoke_agent(agent, f"다음 GitHub URL의 파일을 읽고 정보를 추출해주세요: {state['github_url']}")

        raw_code, comments = _parse_code_review(raw)
        logger.info("Code Reviewer 완료")
        return {**state, "raw_code": raw_code, "comments": comments, "error": None}

    except Exception as e:
        logger.error("Code Reviewer 실패: %s", e)
        return {**state, "error": f"[CodeReviewer] {e}"}


async def analyzer_node(state: CodeNoteState) -> CodeNoteState:
    logger.info("Analyzer 시작")
    try:
        llm = ChatAnthropic(model="claude-opus-4-6", thinking={"type": "adaptive"})
        messages = [
            SystemMessage(content=_ANALYZER_PROMPT),
            HumanMessage(content=(
                f"## 코드 원문\n```\n{state['raw_code']}\n```\n\n"
                f"## 작성자 주석\n{state['comments']}\n\n"
                "위 코드를 분석해주세요."
            )),
        ]
        analysis = await _invoke_llm(llm, messages)

        logger.info("Analyzer 완료")
        return {**state, "analysis": analysis, "error": None}

    except Exception as e:
        logger.error("Analyzer 실패: %s", e)
        return {**state, "error": f"[Analyzer] {e}"}


async def markdown_writer_node(state: CodeNoteState) -> CodeNoteState:
    logger.info("Markdown Writer 시작")
    try:
        # Step 1: 마크다운 작성
        llm = ChatAnthropic(model="claude-opus-4-6")
        title = _extract_title(state["github_url"])
        messages = [
            SystemMessage(content=_MARKDOWN_WRITER_PROMPT),
            HumanMessage(content=(
                f"문제 이름: {title}\n\n"
                f"## 코드 원문\n```\n{state['raw_code']}\n```\n\n"
                f"## 주석\n{state['comments']}\n\n"
                f"## 분석 결과\n{state['analysis']}\n\n"
                "위 내용을 바탕으로 학습 노트를 작성해주세요."
            )),
        ]
        markdown_note = await _invoke_llm(llm, messages)
        logger.info("마크다운 작성 완료 (%d자)", len(markdown_note))

        # Step 2: Notion 업로드
        async with MultiServerMCPClient({"notion": notion_mcp_config()}) as client:
            tools = client.get_tools()
            upload_llm = ChatAnthropic(model="claude-opus-4-6")
            agent = create_react_agent(upload_llm, tools, state_modifier=_NOTION_UPLOAD_PROMPT)
            await _invoke_agent(
                agent,
                f"Notion Database에 새 페이지를 생성해주세요.\n\n"
                f"Database ID: {state['notion_database_id']}\n"
                f"페이지 제목: {title}\n\n"
                f"내용:\n{markdown_note}"
            )

        logger.info("Notion 업로드 완료: %s", title)
        return {**state, "markdown_note": markdown_note, "error": None}

    except Exception as e:
        logger.error("Markdown Writer 실패: %s", e)
        return {**state, "error": f"[MarkdownWriter] {e}"}
