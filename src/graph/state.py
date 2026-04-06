from typing import TypedDict


class CodeNoteState(TypedDict):
    github_url: str
    notion_database_id: str   # Notion Database ID (고정값, 환경변수로 관리)
    raw_code: str | None      # code_reviewer: 코드 원문
    comments: str | None      # code_reviewer: 추출한 주석
    analysis: str | None      # analyzer: 알고리즘 분석 결과
    markdown_note: str | None # markdown_writer: 완성된 학습 노트
    error: str | None
