import logging

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from src.graph.state import CodeNoteState
from src.utils.retry import agent_retry

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 알고리즘 전문가이자 교육자입니다.
주어진 코드와 주석을 읽고, 아래 항목을 깊이 있게 분석하세요.
분석 결과는 다음 단계에서 학습 노트 작성에 사용됩니다.

---

## 추출할 항목

### 1. 문제 정의
- 입력 조건 (타입, 범위, 제약)
- 출력 조건
- 주의사항 (예: "전체 문자열을 매칭해야 함")

### 2. 핵심 알고리즘 선택 이유
- 어떤 알고리즘/자료구조를 사용했는가
- 왜 이 알고리즘인가? (brute force 대비 장점, 문제 구조와의 연결)
- Overlapping Subproblems, Optimal Substructure 등 이론적 근거가 있다면 명시

### 3. 핵심 아이디어 및 점화식
- 핵심 변수 정의 (예: dp[i][j]가 의미하는 것)
- 점화식 또는 전이 조건 (각 케이스별로 분리)
- 각 케이스가 왜 그렇게 되는지 reasoning 포함
- 반직관적이거나 헷갈리기 쉬운 부분은 Q&A 형태로 설명

### 4. Base case 및 초기화
- Base case 정의 및 이유
- 초기값 설정 방법

### 5. 알고리즘 단계별 흐름
- 구체적인 실행 순서 (numbered list)
- 각 단계의 코드 스니펫과 설명
- 필요한 경우 표(table)로 케이스 정리

### 6. 복잡도 분석
- 시간 복잡도 (Big-O, 이유 포함)
- 공간 복잡도

### 7. 이 유형에서 기억할 패턴
- 이 알고리즘 유형의 공통 패턴
- 비슷한 문제에 적용할 때 체크포인트

---

주석에 작성자의 설명이 있다면 최대한 활용하세요.
수식이나 논리는 정확하게 작성하세요."""


@agent_retry(max_attempts=3)
async def _invoke(llm, messages) -> str:
    response = await llm.ainvoke(messages)
    return response.content


async def analyzer_node(state: CodeNoteState) -> CodeNoteState:
    logger.info("Analyzer 시작")
    try:
        llm = ChatAnthropic(
            model="claude-opus-4-6",
            thinking={"type": "adaptive"},
        )
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=(
                f"## 코드 원문\n```\n{state['raw_code']}\n```\n\n"
                f"## 작성자 주석\n{state['comments']}\n\n"
                "위 코드를 분석해주세요."
            )),
        ]
        analysis = await _invoke(llm, messages)

        logger.info("Analyzer 완료")
        return {**state, "analysis": analysis, "error": None}

    except Exception as e:
        logger.error("Analyzer 실패: %s", e)
        return {**state, "error": f"[Analyzer] {e}"}
