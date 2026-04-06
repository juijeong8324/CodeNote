import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from src.graph.state import CodeNoteState
from src.graph.workflow import codenote_workflow
from src.models.schemas import CodeNoteRequest, CodeNoteResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("CodeNote 서버 시작")
    yield
    logger.info("CodeNote 서버 종료")


app = FastAPI(
    title="CodeNote API",
    description="알고리즘 학습 노트 자동 생성 Agent",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/api/v1/notes", response_model=CodeNoteResponse)
async def create_note(request: CodeNoteRequest):
    logger.info("학습 노트 생성 요청: %s", request.github_url)

    initial_state: CodeNoteState = {
        "github_url": request.github_url,
        "notion_database_id": request.notion_database_id,
        "raw_code": None,
        "comments": None,
        "analysis": None,
        "markdown_note": None,
        "error": None,
    }

    final_state: CodeNoteState = await codenote_workflow.ainvoke(initial_state)

    if final_state.get("error"):
        raise HTTPException(status_code=500, detail=final_state["error"])

    note = final_state.get("markdown_note", "")
    title = request.github_url.rstrip("/").split("/")[-1].rsplit(".", 1)[0]

    return CodeNoteResponse(
        success=True,
        title=title,
        notion_database_id=request.notion_database_id,
        summary=note[:300] + "..." if len(note) > 300 else note,
    )
