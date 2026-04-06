import logging

from langchain_anthropic import ChatAnthropic
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from src.graph.state import CodeNoteState
from src.mcp.config import notion_mcp_config
from src.utils.retry import agent_retry

logger = logging.getLogger(__name__)

WRITE_SYSTEM_PROMPT = """당신은 알고리즘 학습 노트를 작성하는 전문가입니다.
분석 결과를 바탕으로 아래 형식에 맞게 마크다운 학습 노트를 작성하세요.

---

## 형식 규칙

- 제목은 문제 이름으로
- 각 섹션은 `##` 헤딩 사용
- 코드 블록은 언어 명시 (```python, ```cpp 등)
- 핵심 수식/조건은 인라인 코드(`) 또는 코드 블록으로 표시
- 케이스 비교가 필요한 경우 표(table) 사용
- 반직관적이거나 헷갈리기 쉬운 부분은 반드시 **Q&A 형태**로 설명
- `<br>` 태그로 섹션 간 여백 확보

---

## 출력 형식

```markdown
# {문제 이름}

## Problem

- **Input**
  - 변수명, 타입, 범위 등
- **Output**
  - 출력 조건
  - 주의사항

<br>
<br>

## Key point

- 핵심 변수 정의 (예: `dp[i][j]`가 의미하는 것)
- 왜 이 알고리즘인가? (이론적 근거 포함)

<br>

- Q. (반직관적이거나 헷갈리는 부분 질문)
- A. (명확한 설명)

<br>

- Base case 정의 및 이유
  - 예시와 함께 설명

<br>
<br>

## Algorithm Approach

1. 첫 번째 단계 설명

<br>

2. 두 번째 단계

```python
# 코드 스니펫
```

<br>

3. 케이스별 점화식

   **Case 1) 조건**

```python
# 점화식
```

| 경우 | 식 | 의미 |
| ---- | -- | ---- |
| ...  | ...| ...  |

> **🤔 왜 A가 아니라 B인가?**
> 설명

<br>

   **Case 2) 조건**

```python
# 점화식
```

- 설명

<br>

## 복잡도

- **시간 복잡도**: O(...) — 이유
- **공간 복잡도**: O(...) — 이유

<br>

## 이 유형에서 기억할 것

- 핵심 패턴 1
- 핵심 패턴 2
```"""

UPLOAD_SYSTEM_PROMPT = """당신은 Notion에 콘텐츠를 업로드하는 에이전트입니다.
Notion MCP 도구를 사용해 지정된 Database에 새 페이지를 생성하고 마크다운 내용을 작성하세요.
업로드 완료 후 생성된 페이지 URL을 반환하세요."""


@agent_retry(max_attempts=3)
async def _write_markdown(llm, messages) -> str:
    response = await llm.ainvoke(messages)
    return response.content


@agent_retry(max_attempts=3)
async def _upload_to_notion(agent, notion_database_id: str, title: str, markdown: str) -> str:
    result = await agent.ainvoke({
        "messages": [("user", (
            f"Notion Database에 새 페이지를 생성해주세요.\n\n"
            f"Database ID: {notion_database_id}\n"
            f"페이지 제목: {title}\n\n"
            f"내용:\n{markdown}"
        ))]
    })
    return result["messages"][-1].content


def _extract_title(raw_code: str, github_url: str) -> str:
    """파일명에서 제목을 추출합니다."""
    filename = github_url.rstrip("/").split("/")[-1]
    # 확장자 제거
    title = filename.rsplit(".", 1)[0] if "." in filename else filename
    return title.replace("_", " ").replace("-", " ")


async def markdown_writer_node(state: CodeNoteState) -> CodeNoteState:
    logger.info("Markdown Writer 시작")
    try:
        # Step 1: 마크다운 학습 노트 작성
        llm = ChatAnthropic(model="claude-opus-4-6")
        title = _extract_title(state["raw_code"], state["github_url"])
        messages = [
            SystemMessage(content=WRITE_SYSTEM_PROMPT),
            HumanMessage(content=(
                f"문제 이름: {title}\n\n"
                f"## 코드 원문\n```\n{state['raw_code']}\n```\n\n"
                f"## 주석\n{state['comments']}\n\n"
                f"## 분석 결과\n{state['analysis']}\n\n"
                "위 내용을 바탕으로 학습 노트를 작성해주세요."
            )),
        ]
        markdown_note = await _write_markdown(llm, messages)
        logger.info("마크다운 작성 완료 (%d자)", len(markdown_note))

        # Step 2: Notion Database에 새 페이지 생성
        async with MultiServerMCPClient({"notion": notion_mcp_config()}) as client:
            tools = client.get_tools()
            upload_llm = ChatAnthropic(model="claude-opus-4-6")
            agent = create_react_agent(upload_llm, tools, state_modifier=UPLOAD_SYSTEM_PROMPT)
            await _upload_to_notion(
                agent,
                state["notion_database_id"],
                title,
                markdown_note,
            )

        logger.info("Notion 업로드 완료: %s", title)
        return {**state, "markdown_note": markdown_note, "error": None}

    except Exception as e:
        logger.error("Markdown Writer 실패: %s", e)
        return {**state, "error": f"[MarkdownWriter] {e}"}
