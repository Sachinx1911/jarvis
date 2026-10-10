"""Projects and documents in the dashboard: list/create projects, edit PROJECT.md, upload
documents into projects/<name>/docs/, index, set privacy P1/P2, search with citations.

Everything runs locally; no model is called here. Every change is audit-logged.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from jarvis.docs.library import DocError
from jarvis.projects import ProjectStore, valid_name
from jarvis.web.context import WebContext
from jarvis.web.uploads import MAX_UPLOAD_BYTES, UploadError, save_upload

MAX_PROJECT_MD = 100_000


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    goal: str = Field(default="", max_length=2000)


class ProjectText(BaseModel):
    text: str = Field(max_length=MAX_PROJECT_MD)


class IndexBody(BaseModel):
    force: bool = False


class PrivacyBody(BaseModel):
    file: str = Field(min_length=1, max_length=300)
    privacy: Literal["P1", "P2"]


def _library(rt):
    from jarvis.connectors.registry import ConnectorDeps, doc_library

    # max_privacy P2: the dashboard is Sachin's own screen on this machine (like the terminal).
    return doc_library(ConnectorDeps(rt.paths.home, rt.store, rt.audit, max_privacy="P2"))


def _goal(md: str) -> str:
    lines = md.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower() == "## goal":
            for nxt in lines[i + 1:]:
                if nxt.startswith("#"):
                    break
                if nxt.strip():
                    return nxt.strip()[:200]
    return ""


def build_router(ctx: WebContext) -> APIRouter:
    r = APIRouter()

    def project_name(rt, name: str) -> str:
        try:
            slug = valid_name(name)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if slug != name:
            raise HTTPException(400, "invalid project name")
        if not ProjectStore(rt.paths.home).exists(slug):
            raise HTTPException(404, f"no project {name}")
        return slug

    def docs_json(lib, name: str) -> list[dict[str, Any]]:
        indexed = {d.file: d for d in lib.documents(name)}
        out = []
        docs_dir = lib.docs_dir(name)
        on_disk = sorted(p.relative_to(docs_dir).as_posix() for p in docs_dir.rglob("*")
                         if p.is_file() and not any(part.startswith((".", "~$")) for part in p.relative_to(docs_dir).parts)
                         ) if docs_dir.is_dir() else []
        for f in sorted(set(on_disk) | set(indexed)):
            d = indexed.get(f)
            out.append({"file": f, "indexed": d is not None, "privacy": d.privacy if d else "P2",
                        "chunks": d.chunks if d else 0, "status": d.status if d else "not indexed",
                        "error": d.error if d else None, "doc_date": d.doc_date if d else None,
                        "on_disk": f in on_disk})
        return out

    @r.get("/projects")
    def projects() -> dict[str, Any]:
        with ctx.runtime() as rt:
            store = ProjectStore(rt.paths.home)
            lib = _library(rt)
            counts: dict[str, int] = {}
            for d in lib.documents():
                counts[d.project] = counts.get(d.project, 0) + 1
            items = [{"name": n, "goal": _goal(store.context(n)), "documents": counts.get(n, 0)} for n in store.list()]
            return {"items": items}

    @r.post("/projects")
    def project_create(body: ProjectCreate) -> dict[str, Any]:
        with ctx.runtime() as rt:
            store = ProjectStore(rt.paths.home)
            try:
                slug = valid_name(body.name)
            except ValueError as e:
                raise HTTPException(400, str(e))
            existed = store.exists(slug)
            store.create(slug, body.goal.strip())
            rt.audit.write("project_created" if not existed else "project_exists", source="dashboard", project=slug)
            return {"name": slug, "created": not existed}

    @r.get("/projects/{name}")
    def project_show(name: str) -> dict[str, Any]:
        with ctx.runtime() as rt:
            slug = project_name(rt, name)
            md = rt.paths.home / "projects" / slug / "PROJECT.md"
            lib = _library(rt)
            return {"name": slug, "project_md": md.read_text(encoding="utf-8"), "documents": docs_json(lib, slug),
                    "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024)}

    @r.put("/projects/{name}/md")
    def project_md(name: str, body: ProjectText) -> dict[str, Any]:
        with ctx.runtime() as rt:
            slug = project_name(rt, name)
            if not body.text.strip():
                raise HTTPException(400, "PROJECT.md cannot be empty")
            md = rt.paths.home / "projects" / slug / "PROJECT.md"
            md.write_text(body.text.replace("\r\n", "\n"), encoding="utf-8")
            rt.audit.write("project_md_edited", source="dashboard", project=slug, chars=len(body.text))
            return {"name": slug, "saved": True}

    def _upload(name: str, filename: str, data: bytes, replace: bool) -> dict[str, Any]:
        with ctx.runtime() as rt:
            slug = project_name(rt, name)
            lib = _library(rt)
            try:
                path = save_upload(lib.docs_dir(slug), filename, data, replace=replace)
            except FileExistsError as e:
                raise HTTPException(409, f"{e} already exists; tick 'replace' to overwrite it")
            except UploadError as e:
                rt.audit.write("document_upload_refused", source="dashboard", project=slug, reason=str(e))
                raise HTTPException(400, str(e))
            rel = path.name
            rt.audit.write("document_uploaded", source="dashboard", project=slug, file=rel, bytes=len(data),
                           replaced=replace)
            report = lib.index(slug)
            rt.audit.write("docs_index", source="dashboard", project=slug, added=len(report.added),
                           updated=len(report.updated), removed=len(report.removed), failed=len(report.failed))
            return {"file": rel, "index": report.summary(),
                    "failed": [{"file": f, "why": w} for f, w in report.failed]}

    @r.post("/projects/{name}/docs")
    async def project_upload(name: str, request: Request, filename: str, replace: bool = False) -> dict[str, Any]:
        # Raw body (application/octet-stream) with the name in the query: no multipart parser needed.
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"the file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(413, f"the file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
            chunks.append(chunk)
        return await run_in_threadpool(_upload, name, filename, b"".join(chunks), replace)

    @r.post("/projects/{name}/index")
    def project_index(name: str, body: IndexBody) -> dict[str, Any]:
        with ctx.runtime() as rt:
            slug = project_name(rt, name)
            report = _library(rt).index(slug, force=body.force)
            rt.audit.write("docs_index", source="dashboard", project=slug, added=len(report.added),
                           updated=len(report.updated), removed=len(report.removed), failed=len(report.failed))
            return {"summary": report.summary(), "failed": [{"file": f, "why": w} for f, w in report.failed]}

    @r.post("/projects/{name}/privacy")
    def project_privacy(name: str, body: PrivacyBody) -> dict[str, Any]:
        with ctx.runtime() as rt:
            slug = project_name(rt, name)
            try:
                rel = _library(rt).mark(slug, body.file, body.privacy)
            except DocError as e:
                raise HTTPException(400, str(e))
            rt.audit.write("docs_mark", source="dashboard", project=slug, file=rel, privacy=body.privacy)
            return {"file": rel, "privacy": body.privacy}

    @r.get("/docs/search")
    def docs_search(q: str = "", project: str = "", k: int = 8) -> dict[str, Any]:
        if not q.strip():
            return {"items": []}
        with ctx.runtime() as rt:
            slug = project_name(rt, project) if project else None
            hits = _library(rt).search(q, project=slug, k=max(1, min(k, 20)))
            return {"items": [{"citation": h.citation(), "project": h.project, "file": h.file, "page": h.page,
                               "section": h.section, "privacy": h.privacy, "doc_date": h.doc_date,
                               "text": h.text[:800], "score": round(h.score, 4)} for h in hits]}

    return r
