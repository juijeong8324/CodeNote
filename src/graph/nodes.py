import logging
import os
import re
from pathlib import Path

#from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI 
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent

from src.graph.state import (
    CodeNoteState,
    FileContent,
    ProblemAnalysis,
    ProblemResult,
)
from src.mcp.config import github_mcp_config # Get MCP setting
from src.utils.retry import agent_retry

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# ====================== Set LLM ======================
# _llm = ChatAnthropic(model="claude-opus-4-6")
# _llm_thinking = ChatAnthropic(model="claude-opus-4-6", thinking={"type": "adaptive"})

_llm = ChatGoogleGenerativeAI(
    model="gemini-3.1-flash-lite-preview",   # 가장 빠르고 저렴
    # model="gemini-2.5-flash",              # 대안 (조금 더 안정적)
    temperature=0.1,
    max_tokens=8192,
    google_api_key=os.getenv("GEMINI_API_KEY"),
)

# Thinking / 깊은 분석용
_llm_thinking = ChatGoogleGenerativeAI(
    model="gemini-3.1-flash-lite-preview",
    temperature=0.15,
    max_tokens=16384,
    # Gemini는 thinking_budget으로 제어 (adaptive 비슷한 효과)
    thinking_budget=-1,   # 동적 thinking (Gemini 2.5/3.1 지원 시)
    google_api_key=os.getenv("GEMINI_API_KEY"),
)



# ====================== Prompts ======================

def load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


_CODE_REVIEWER_PROMPT = load_prompt("code_reviewer")
_ANALYZER_PROMPT = load_prompt("analyzer")
_MARKDOWN_WRITER_PROMPT = load_prompt("markdown_writer")
_GITHUB_PUBLISHER_PROMPT = load_prompt("github_publisher")


# ====================== Helpers ======================

_NOTE_FILENAME = os.getenv("NOTE_FILENAME", "Solution.md")

_EXT_TO_LANG = {
    "py": "Python", "cpp": "C++", "c": "C", "java": "Java",
    "js": "JavaScript", "ts": "TypeScript", "go": "Go",
    "rs": "Rust", "cs": "C#", "kt": "Kotlin", "rb": "Ruby",
}


def _lang(filename: str) -> str:
    """Derive language name from file extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _EXT_TO_LANG.get(ext, ext.upper())


def _get_filename(file_url: str) -> str:
    return file_url.rstrip("/").split("/")[-1]

# Folder Grouping
def _extract_folder(file_url: str) -> str:
    if "/blob/" in file_url:
        after_blob = file_url.split("/blob/", 1)[1]
        path = after_blob.split("/", 1)[1] if "/" in after_blob else after_blob
    else:
        path = file_url
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _extract_note_path(folder: str) -> str:
    return f"{folder}/{_NOTE_FILENAME}" if folder else _NOTE_FILENAME


def _extract_repo_info(repo_url: str) -> tuple[str, str]:
    parts = repo_url.rstrip("/").split("/")
    return parts[-2], parts[-1]


def _pick_primary(files: list[FileContent]) -> FileContent:
    for target in ("py", "cpp"):
        for f in files:
            if f["filename"].endswith(f".{target}"):
                return f
    return files[0] if files else None


def _parse_multi_file_review(raw: str) -> list[FileContent]:
    """Parse code_reviewer output.
    Expected format:
    ===FILE[filename]===
    (code)
    ===COMMENTS[filename]===
    (comments)
    """
    results = []
    pattern = re.compile(
        r'===FILE\[(.+?)\]===(.*?)(?====FILE\[|\Z)',
        re.DOTALL
    )
    for match in pattern.finditer(raw):
        filename = match.group(1).strip()
        content = match.group(2)

        comment_marker = f"===COMMENTS[{filename}]==="
        if comment_marker in content:
            code, comments = content.split(comment_marker, 1)
        else:
            code, comments = content, ""

        results.append(FileContent(
            filename=filename,
            raw_code=code.strip(),
            comments=comments.strip(),
        ))

    # Fallback: treat entire output as a single unknown file
    if not results:
        results.append(FileContent(
            filename="unknown",
            language="Unknown",
            raw_code=raw.strip(),
            comments="",
        ))

    return results


# invoke helpers

@agent_retry(max_attempts=3)
async def _invoke_agent(agent, message: str) -> str:
    result = await agent.ainvoke({"messages": [HumanMessage(content=message)]})
    return result["messages"][-1].content


@agent_retry(max_attempts=3)
async def _invoke_llm(llm, messages) -> str:
    response = await llm.ainvoke(messages)
    return response.content


# nodes

def coordinator_node(state: CodeNoteState) -> dict:
    """Group files by folder (one folder = one problem)."""
    groups: dict[str, list[str]] = {}
    for file_url in state["files"]:
        folder = _extract_folder(file_url)
        groups.setdefault(folder, []).append(file_url)

    problems = [
        {"folder": folder, "file_urls": urls}
        for folder, urls in groups.items()
    ]
    logger.info(
        "[Coordinator] %d files -> %d problem groups",
        len(state["files"]), len(problems)
    )
    for p in problems:
        logger.info("  [%s] %s", p["folder"], [_get_filename(u) for u in p["file_urls"]])
    return {"problems": problems}


def supervisor_node(state: CodeNoteState) -> CodeNoteState:
    """Entry point for MAP fan-out to code_analyzer."""
    logger.info("[Supervisor] dispatching %d problem groups", len(state["problems"]))
    return state


async def code_analyzer_node(state: ProblemAnalysis) -> dict:
    logger.info("[Code Analyzer] start: %s (%d files)", state["folder"], len(state["file_urls"]))
    try:
        # Step 1: Read all files via GitHub MCP
        file_list = "\n".join(f"- {url}" for url in state["file_urls"])

        # EKS 배포에 적합한 Remote MCP 사용
        async with MultiServerMCPClient({"github": github_mcp_config()}) as client:
            tools = await client.get_tools() # add Await
            agent = create_react_agent(_llm, tools, state_modifier=_CODE_REVIEWER_PROMPT)
            raw = await _invoke_agent(
                agent,
                f"Please read all files at the following GitHub URLs and extract information:\n{file_list}"
            )
        files = _parse_multi_file_review(raw)

        # Step 2: Analyze — primary file in depth, compare others
        primary = _pick_primary(files)
        others = [f for f in files if f["filename"] != primary["filename"]]

        files_section = (
            f"## Primary File: {primary['filename']} ({_lang(primary['filename'])})\n"
            f"```{_lang(primary['filename']).lower()}\n{primary['raw_code']}\n```\n"
            f"### Author Comments\n{primary['comments'] or 'No comments'}\n"
        )
        if others:
            files_section += "\n## Additional Files\n"
            for f in others:
                files_section += (
                    f"### {f['filename']} ({_lang(f['filename'])})\n"
                    f"```{_lang(f['filename']).lower()}\n{f['raw_code']}\n```\n"
                    f"#### Comments\n{f['comments'] or 'No comments'}\n"
                )

        messages = [
            SystemMessage(content=_ANALYZER_PROMPT),
            HumanMessage(content=f"{files_section}\nPlease analyze the code above."),
        ]
        analysis = await _invoke_llm(_llm_thinking, messages)

        logger.info("[Code Analyzer] done: %s", state["folder"])
        return {"analyzed": [ProblemAnalysis(
            folder=state["folder"],
            file_urls=state["file_urls"],
            files=files,
            analysis=analysis,
            error=None,
        )]}

    except Exception as e:
        logger.error("[Code Analyzer] failed [%s]: %s", state["folder"], e)
        return {"analyzed": [ProblemAnalysis(
            folder=state["folder"],
            file_urls=state["file_urls"],
            files=None,
            analysis=None,
            error=f"[CodeAnalyzer] {e}",
        )]}


async def doc_writer_node(state: ProblemAnalysis) -> dict:
    logger.info("[Doc Writer] start: %s", state["folder"])
    try:
        problem_name = state["folder"].rstrip("/").split("/")[-1]
        files = state["files"] or []
        primary = _pick_primary(files) if files else None
        others = [f for f in files if f["filename"] != primary["filename"]] if primary else []

        files_section = ""
        if primary:
            files_section += (
                f"## Primary File: {primary['filename']} ({_lang(primary['filename'])})\n"
                f"```{_lang(primary['filename']).lower()}\n{primary['raw_code']}\n```\n"
                f"### Comments\n{primary['comments'] or 'No comments'}\n"
            )
        if others:
            files_section += "\n## Additional Files\n"
            for f in others:
                files_section += (
                    f"### {f['filename']} ({_lang(f['filename'])})\n"
                    f"```{_lang(f['filename']).lower()}\n{f['raw_code']}\n```\n"
                )

        messages = [
            SystemMessage(content=_MARKDOWN_WRITER_PROMPT),
            HumanMessage(content=(
                f"Problem name: {problem_name}\n\n"
                f"{files_section}\n"
                f"## Analysis\n{state['analysis']}\n\n"
                "Please write a study note based on the above."
            )),
        ]
        markdown_note = await _invoke_llm(_llm, messages)

        logger.info("[Doc Writer] done: %s (%d chars)", problem_name, len(markdown_note))
        return {"results": [ProblemResult(
            folder=state["folder"],
            markdown_note=markdown_note,
            error=None,
        )]}

    except Exception as e:
        logger.error("[Doc Writer] failed [%s]: %s", state["folder"], e)
        return {"results": [ProblemResult(
            folder=state["folder"],
            markdown_note=None,
            error=f"[DocWriter] {e}",
        )]}


async def github_publisher_node(state: CodeNoteState) -> CodeNoteState:
    """[REDUCE] Push all notes in a single commit via push_files."""
    successful = [r for r in state["results"] if not r.get("error") and r.get("markdown_note")]
    logger.info("[GitHub Publisher] start: pushing %d notes", len(successful))

    if not successful:
        logger.warning("[GitHub Publisher] no notes to upload")
        return state

    try:
        owner, repo = _extract_repo_info(state["repo_url"])

        files_info = "\n\n---\n\n".join([
            f"File path: {_extract_note_path(r['folder'])}\n"
            f"Content:\n{r['markdown_note']}"
            for r in successful
        ])

        async with MultiServerMCPClient({"github": github_mcp_config()}) as client:
            tools = await client.get_tools()
            agent = create_react_agent(_llm, tools, state_modifier=_GITHUB_PUBLISHER_PROMPT)
            await _invoke_agent(
                agent,
                f"Please push the following markdown files to GitHub in a single commit.\n\n"
                f"Owner: {owner}\n"
                f"Repo: {repo}\n"
                f"Branch: {state['branch']}\n"
                f"Commit message: docs: add study notes ({len(successful)} files)\n\n"
                f"{files_info}"
            )

        logger.info("[GitHub Publisher] push complete: %d notes", len(successful))

    except Exception as e:
        logger.error("[GitHub Publisher] failed: %s", e)

    return state
