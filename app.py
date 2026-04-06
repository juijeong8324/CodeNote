import hashlib
import hmac
import logging
import os
from contextlib import asynccontextmanager

import uvicorn

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from src.graph.builder import codenote_graph
from src.graph.state import CodeNoteState

# ---------- Env ----------
load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "")

HOST = "0.0.0.0"
PORT = "8080"

# ---------- App ----------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[CodeNote] Server Start")
    yield
    logger.info("[CodeNote] Server End")


app = FastAPI(
    title="CodeNote API",
    description="Create Code Note by Agent",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------- Helpers ----------

def _verify_signature(body: bytes, signature: str) -> bool:
    if not WEBHOOK_SECRET:
        return True
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _run_workflow(github_url: str) -> None:
    state: CodeNoteState = {
        "github_url": github_url,
        "notion_database_id": NOTION_DATABASE_ID,
        "raw_code": None,
        "comments": None,
        "analysis": None,
        "markdown_note": None,
        "error": None,
    }
    result = await codenote_graph.ainvoke(state)
    if result.get("error"):
        logger.error("워크플로우 실패 [%s]: %s", github_url, result["error"])
    else:
        logger.info("노트 생성 완료: %s", github_url)

# ---------- Models ----------

class CodeNoteRequest(BaseModel):
    github_url: str
    notion_database_id: str


class CodeNoteResponse(BaseModel):
    success: bool
    title: str
    notion_database_id: str
    summary: str
    error: str | None = None

# ---------- Routes ----------

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

    final_state: CodeNoteState = await codenote_graph.ainvoke(initial_state)

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


@app.post("/webhook")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
):
    body = await request.body()

    if x_hub_signature_256 and not _verify_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    if x_github_event != "push":
        return {"status": "ignored", "event": x_github_event}

    payload = await request.json()
    repo_url = payload.get("repository", {}).get("html_url", "")
    branch = payload.get("ref", "refs/heads/main").split("/")[-1]

    changed_files: list[str] = []
    for commit in payload.get("commits", []):
        changed_files.extend(commit.get("added", []))
        changed_files.extend(commit.get("modified", []))
    changed_files = list(dict.fromkeys(changed_files))

    if not changed_files:
        return {"status": "no files changed"}

    for file_path in changed_files:
        file_url = f"{repo_url}/blob/{branch}/{file_path}"
        background_tasks.add_task(_run_workflow, file_url)
        logger.info("워크플로우 예약: %s", file_url)

    return {"status": "accepted", "files": len(changed_files)}


# main

if __name__ == "__main__":
    logger.info("[CodeNote] Starting server on %s:%s", HOST, PORT)
    uvicorn.run(app, host=HOST, port=PORT)
