from pydantic import BaseModel


class CodeNoteRequest(BaseModel):
    github_url: str             # 분석할 파일의 GitHub URL
    notion_database_id: str     # 학습 노트를 생성할 Notion Database ID


class CodeNoteResponse(BaseModel):
    success: bool
    title: str                  # 생성된 노트 제목 (파일명 기반)
    notion_database_id: str
    summary: str                # 마크다운 앞부분 미리보기
    error: str | None = None
