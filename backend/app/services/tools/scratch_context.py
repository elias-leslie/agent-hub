"""Transient scratch artifacts for large direct-tool output."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

DEFAULT_PREVIEW_CHARS = 4_000
DEFAULT_SEARCH_LIMIT = 5
MAX_SEARCH_LIMIT = 20
MAX_CONTEXT_LINES = 8
SEARCH_ARTIFACT_SCAN_LIMIT = 50
CHUNK_TARGET_CHARS = 8_000
SCRATCH_CONTEXT_ENV = "AGENT_HUB_SCRATCH_CONTEXT_DIR"


@dataclass(frozen=True)
class ScratchArtifactSummary:
    artifact_id: str
    source: str
    label: str
    path: Path
    byte_count: int
    char_count: int
    line_count: int
    chunk_count: int
    created_at: str


@dataclass(frozen=True)
class ScratchOutputResult:
    content: str
    artifact_id: str | None
    raw_chars: int
    returned_chars: int
    saved_chars: int


def _safe_part(value: str | None, fallback: str) -> str:
    text = (value or "").strip() or fallback
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)[:96] or fallback


def _token_estimate(chars: int) -> int:
    return max(1, (max(chars, 0) + 3) // 4)


def _clamp_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 28)].rstrip() + "\n... [truncated]"


def _preview(text: str, limit: int = DEFAULT_PREVIEW_CHARS) -> str:
    if len(text) <= limit:
        return text
    head = max(1, (limit * 2) // 3)
    tail = max(1, limit - head)
    return (
        text[:head].rstrip()
        + "\n... [scratch preview truncated; search artifact for full output] ...\n"
        + text[-tail:].lstrip()
    )


def _build_chunks(text: str) -> list[dict[str, int]]:
    chunks: list[dict[str, int]] = []
    line_start = 1
    offset_start = 0
    current_chars = 0
    current_line = 1
    offset = 0

    for line in text.splitlines(keepends=True):
        current_chars += len(line)
        offset += len(line)
        if current_chars >= CHUNK_TARGET_CHARS:
            chunks.append(
                {
                    "chunk": len(chunks) + 1,
                    "start_line": line_start,
                    "end_line": current_line,
                    "start_offset": offset_start,
                    "end_offset": offset,
                }
            )
            line_start = current_line + 1
            offset_start = offset
            current_chars = 0
        current_line += 1

    line_count = len(text.splitlines())
    if offset_start < len(text) or not chunks:
        chunks.append(
            {
                "chunk": len(chunks) + 1,
                "start_line": line_start,
                "end_line": max(line_start, line_count),
                "start_offset": offset_start,
                "end_offset": len(text),
            }
        )
    return chunks


def inline_output_result(text: str) -> ScratchOutputResult:
    returned = text or "(no output)"
    return ScratchOutputResult(
        content=returned,
        artifact_id=None,
        raw_chars=len(returned),
        returned_chars=len(returned),
        saved_chars=0,
    )


class ScratchContextStore:
    """File-backed transient store for model-visible scratch artifacts."""

    def __init__(self, root: Path | None = None) -> None:
        env_root = os.getenv(SCRATCH_CONTEXT_ENV)
        default_root = Path(tempfile.gettempdir()) / "agent-hub-scratch-context"
        self.root = Path(root or env_root or default_root).expanduser().resolve()

    def _artifact_path(self, project_id: str | None, session_id: str | None, artifact_id: str) -> Path:
        return (
            self.root
            / _safe_part(project_id, "no-project")
            / _safe_part(session_id, "no-session")
            / f"{artifact_id}.json"
        )

    def store_text(
        self,
        text: str,
        *,
        source: str,
        label: str,
        project_id: str | None,
        session_id: str | None,
        agent_slug: str | None,
        working_dir: Path | None,
    ) -> ScratchArtifactSummary:
        artifact_id = f"scratch_{uuid4().hex[:12]}"
        created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        chunks = _build_chunks(text)
        path = self._artifact_path(project_id, session_id, artifact_id)
        payload = {
            "artifact_id": artifact_id,
            "source": source,
            "label": label,
            "project_id": project_id,
            "session_id": session_id,
            "agent_slug": agent_slug,
            "working_dir": str(working_dir) if working_dir else None,
            "created_at": created_at,
            "byte_count": len(text.encode("utf-8")),
            "char_count": len(text),
            "line_count": len(text.splitlines()),
            "chunks": chunks,
            "text": text,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f".{uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(path)
        return ScratchArtifactSummary(
            artifact_id=artifact_id,
            source=source,
            label=label,
            path=path,
            byte_count=payload["byte_count"],
            char_count=payload["char_count"],
            line_count=payload["line_count"],
            chunk_count=len(chunks),
            created_at=created_at,
        )

    def prepare_output(
        self,
        text: str,
        *,
        threshold: int,
        source: str,
        label: str,
        project_id: str | None,
        session_id: str | None,
        agent_slug: str | None,
        working_dir: Path | None,
    ) -> ScratchOutputResult:
        output = text or "(no output)"
        if len(output) <= threshold:
            return inline_output_result(output)

        summary = self.store_text(
            output,
            source=source,
            label=label,
            project_id=project_id,
            session_id=session_id,
            agent_slug=agent_slug,
            working_dir=working_dir,
        )
        preview = _preview(output)
        header = "\n".join(
            [
                "SCRATCH_ARTIFACT_INDEXED",
                f"artifact_id: {summary.artifact_id}",
                f"source: {summary.source}",
                f"label: {_clamp_text(summary.label, 180)}",
                (
                    f"stored: {summary.byte_count} bytes, {summary.line_count} lines, "
                    f"{summary.chunk_count} chunks"
                ),
                (
                    "saved_estimate: "
                    f"{_token_estimate(len(output)) - _token_estimate(len(preview))} tokens"
                ),
                (
                    "search: call search_scratch_context with "
                    f'{{"artifact_id":"{summary.artifact_id}","query":"<term>"}}'
                ),
                "preview:",
            ]
        )
        content = f"{header}\n{preview}"
        return ScratchOutputResult(
            content=content,
            artifact_id=summary.artifact_id,
            raw_chars=len(output),
            returned_chars=len(content),
            saved_chars=max(0, len(output) - len(content)),
        )

    def _find_artifact_path(
        self,
        artifact_id: str,
        project_id: str | None,
        session_id: str | None,
    ) -> Path | None:
        if project_id or session_id:
            path = self._artifact_path(project_id, session_id, artifact_id)
            if path.exists():
                return path
        matches = list(self.root.glob(f"*/*/{artifact_id}.json"))
        return matches[0] if matches else None

    def _scope_paths(self, project_id: str | None, session_id: str | None) -> list[Path]:
        if project_id and session_id:
            pattern = self.root / _safe_part(project_id, "no-project") / _safe_part(session_id, "no-session")
            paths = list(pattern.glob("scratch_*.json"))
        elif project_id:
            pattern = self.root / _safe_part(project_id, "no-project")
            paths = list(pattern.glob("*/scratch_*.json"))
        else:
            paths = list(self.root.glob("*/*/scratch_*.json"))
        paths = [path for path in paths if path.is_file()]
        return sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)[:SEARCH_ARTIFACT_SCAN_LIMIT]

    def _load_payload(self, path: Path) -> dict[str, object] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _candidate_payloads(
        self,
        *,
        artifact_id: str | None,
        project_id: str | None,
        session_id: str | None,
    ) -> list[dict[str, object]]:
        if artifact_id:
            path = self._find_artifact_path(artifact_id, project_id, session_id)
            if path is None:
                return []
            payload = self._load_payload(path)
            return [payload] if payload else []

        payloads: list[dict[str, object]] = []
        for path in self._scope_paths(project_id, session_id):
            payload = self._load_payload(path)
            if payload:
                payloads.append(payload)
        return payloads

    def search(
        self,
        *,
        query: str,
        artifact_id: str | None,
        project_id: str | None,
        session_id: str | None,
        limit: int = DEFAULT_SEARCH_LIMIT,
        context_lines: int = 2,
    ) -> str:
        normalized_query = (query or "").strip()
        if not normalized_query:
            return "Error: query is required for scratch search."

        payloads = self._candidate_payloads(
            artifact_id=artifact_id,
            project_id=project_id,
            session_id=session_id,
        )
        if not payloads:
            if artifact_id:
                return f"Error: Scratch artifact not found: {artifact_id}"
            return "No scratch artifacts found for current scope."

        terms = [term for term in re.findall(r"[A-Za-z0-9_.:/-]+", normalized_query.lower()) if term]
        max_results = max(1, min(limit, MAX_SEARCH_LIMIT))
        ctx = max(0, min(context_lines, MAX_CONTEXT_LINES))
        matches: list[tuple[int, str, int, dict[str, object]]] = []

        for payload in payloads:
            text = str(payload.get("text") or "")
            for index, line in enumerate(text.splitlines()):
                score = self._score_line(line, normalized_query, terms)
                if score > 0:
                    matches.append((score, str(payload.get("created_at") or ""), index, payload))

        matches.sort(key=lambda item: (-item[0], item[1], item[2]))
        matches = matches[:max_results]
        if not matches:
            searched = ", ".join(str(payload.get("artifact_id")) for payload in payloads[:5])
            return (
                f"SCRATCH_SEARCH[query={normalized_query!r}|matches=0]\n"
                f"No matches. Artifacts searched: {searched}"
            )

        lines = [
            (
                f"SCRATCH_SEARCH[query={normalized_query!r}|matches={len(matches)}|"
                f"artifacts={len({str(match[3].get('artifact_id')) for match in matches})}]"
            )
        ]
        for score, _, index, payload in matches:
            text_lines = str(payload.get("text") or "").splitlines()
            start = max(0, index - ctx)
            end = min(len(text_lines), index + ctx + 1)
            artifact = str(payload.get("artifact_id") or "unknown")
            label = _clamp_text(str(payload.get("label") or ""), 140).replace("\n", " ")
            lines.append(
                f"\nartifact {artifact} lines {start + 1}-{end} score={score} label={label}"
            )
            for line_index in range(start, end):
                snippet = _clamp_text(text_lines[line_index], 260).replace("\t", "    ")
                lines.append(f"{line_index + 1}: {snippet}")
        return "\n".join(lines)

    @staticmethod
    def _score_line(line: str, query: str, terms: list[str]) -> int:
        lowered = line.lower()
        score = 0
        if query.lower() in lowered:
            score += 10
        for term in terms:
            if term in lowered:
                score += 3
        return score
