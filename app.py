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


async def _run_workflow(state: CodeNoteState) -> None:
    result = await codenote_graph.ainvoke(state)
    errors = [r for r in result.get("results", []) if r.get("error")]
    if errors:
        for e in errors:
            logger.error("워크플로우 실패 [%s]: %s", e["file_url"], e["error"])
    else:
        logger.info("노트 생성 완료: %d개 파일", len(result.get("results", [])))

# ---------- Models ----------

class CodeNoteRequest(BaseModel):
    github_url: str


class CodeNoteResponse(BaseModel):
    success: bool
    title: str
    summary: str
    error: str | None = None

# ---------- Features1: ----------

@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/api/v1/notes", response_model=CodeNoteResponse)
async def create_note(request: CodeNoteRequest):
    logger.info("Request Code Note: %s", request.github_url)

    parts = request.github_url.split("/blob/")
    repo_url = parts[0] if len(parts) == 2 else request.github_url
    rest = parts[1] if len(parts) == 2 else ""
    branch = rest.split("/")[0] if rest else "main"

    initial_state: CodeNoteState = {
        "repo_url": repo_url,
        "branch": branch,
        "files": [request.github_url],
        "analyzed": [],
        "results": [],
    }

    final_state: CodeNoteState = await codenote_graph.ainvoke(initial_state)

    results = final_state.get("results", [])
    if not results or results[0].get("error"):
        error = results[0].get("error") if results else "Unknown error"
        raise HTTPException(status_code=500, detail=error)

    note = results[0].get("markdown_note", "")
    title = request.github_url.rstrip("/").split("/")[-1].rsplit(".", 1)[0]

    return CodeNoteResponse(
        success=True,
        title=title,
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

    # Check Commit messeage
    changed_files: list[str] = []
    for commit in payload.get("commits", []):
        changed_files.extend(commit.get("added", []))
    changed_files = list(dict.fromkeys(changed_files))

    if not changed_files:
        return {"status": "no files changed"}

    initial_state: CodeNoteState = {
        "repo_url": repo_url,
        "branch": branch,
        "files": [f"{repo_url}/blob/{branch}/{fp}" for fp in changed_files],
        "analyzed": [],
        "results": [],
    }

    background_tasks.add_task(_run_workflow, initial_state)
    logger.info("워크플로우 예약: %d개 파일", len(changed_files))

    return {"status": "accepted", "files": len(changed_files)}


# main

if __name__ == "__main__":
    logger.info("[CodeNote] Starting server on %s:%s", HOST, PORT)
    uvicorn.run(app, host=HOST, port=PORT)
