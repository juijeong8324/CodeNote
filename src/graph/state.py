import operator
from typing import Annotated, TypedDict


class ProblemGroup(TypedDict):
    folder: str            # "Dynamic Programming/leetCode/10_Regular Expression Matching"
    file_urls: list[str]   # [main.py url, main.cpp url, ...]


class FileContent(TypedDict):
    filename: str  # "main.py" — language derived from extension
    raw_code: str
    comments: str


class ProblemAnalysis(TypedDict):
    folder: str
    file_urls: list[str]
    files: list[FileContent] | None   
    analysis: str | None
    error: str | None


class ProblemResult(TypedDict):
    folder: str
    markdown_note: str | None
    error: str | None


class CodeNoteState(TypedDict):
    repo_url: str
    branch: str
    files: list[str]                                       
    problems: list[ProblemGroup]                           
    analyzed: Annotated[list[ProblemAnalysis], operator.add]
    results: Annotated[list[ProblemResult], operator.add]
