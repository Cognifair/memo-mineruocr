"""Local splitting/merging and explicitly authorized MinerU v4 cloud steps."""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

API = "https://mineru.net/api/v4"
HOSTS = ("mineru.net", "openxlab.org.cn", "aliyuncs.com", "shlab.tech")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp"}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def inside(root, relative):
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()) or candidate == root.resolve():
        raise ValueError("Path escapes job/output root")
    return candidate


@contextlib.contextmanager
def locked(manifest):
    lock = manifest.with_suffix(".lock")
    # A leftover lock after a crash requires review, never silently steal it.
    with lock.open("x") as handle:
        handle.write(str(os.getpid()))
    try:
        yield
    finally:
        lock.unlink()


def load(manifest):
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not data.get("chunks"):
        raise ValueError("Invalid manifest")
    cursor = 1
    for index, chunk in enumerate(data["chunks"], 1):
        if chunk["id"] != f"part-{index:04d}" or chunk["start"] != cursor or chunk["end"] < cursor:
            raise ValueError("Page ranges must cover the source once in order")
        cursor = chunk["end"] + 1
        source = inside(manifest.parent, chunk["file"])
        if not source.is_file() or sha(source) != chunk["sha256"]:
            raise ValueError("Source chunk missing or changed")
        if source.stat().st_size > data["max_bytes"] or chunk["end"] - chunk["start"] + 1 > data["max_pages"]:
            raise ValueError("Chunk exceeds approved limits")
    if cursor != data["pages"] + 1:
        raise ValueError("Incomplete source coverage")
    return data


def prepare(source, job, max_pages=150, max_mb=180):
    source, job = source.resolve(), job.resolve()
    if not source.is_file() or source.is_symlink():
        raise ValueError("Input must be a real local file")
    if not 1 <= max_pages <= 200 or not 0 < max_mb <= 200:
        raise ValueError("Limits must be positive and no larger than current 200 pages/200 MB")
    if job == source or job in source.parents:
        raise ValueError("Job must not contain the source")
    max_bytes = int(max_mb * 1_000_000)
    reader = None
    if source.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(source)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDF: provide an unlocked copy")
        pages = len(reader.pages)
    elif source.suffix.lower() in IMAGE_EXTS:
        pages = 1
    else:
        raise ValueError("Helper supports PDF/images; use native document tools for other formats")
    if pages < 1:
        raise ValueError("Empty input")
    job.mkdir(parents=True, exist_ok=False)
    (job / "chunks").mkdir()
    (job / "results").mkdir()
    data = {"schema": 1, "source_name": source.name, "source_sha256": sha(source), "pages": pages,
            "max_pages": max_pages, "max_bytes": max_bytes, "chunks": []}

    def materialize(start, end):
        if reader:
            from pypdf import PdfWriter
            writer = PdfWriter()
            for number in range(start - 1, end):
                writer.add_page(reader.pages[number])
            stream = io.BytesIO()
            writer.write(stream)
            content, suffix = stream.getvalue(), ".pdf"
        else:
            content, suffix = source.read_bytes(), source.suffix.lower()
        if len(content) > max_bytes:
            if start == end:
                raise ValueError("One page exceeds size limit; do not silently downsample")
            midpoint = (start + end) // 2
            materialize(start, midpoint)
            materialize(midpoint + 1, end)
            return
        part = f"part-{len(data['chunks']) + 1:04d}"
        relative = f"chunks/{part}{suffix}"
        target = job / relative
        target.write_bytes(content)
        data["chunks"].append({"id": part, "start": start, "end": end, "file": relative,
                               "sha256": sha(target), "bytes": len(content), "state": "prepared"})

    for start in range(1, pages + 1, max_pages):
        materialize(start, min(start + max_pages - 1, pages))
    save(job / "manifest.json", data)
    load(job / "manifest.json")
    return {"status": "prepared", "pages": pages, "chunks": len(data["chunks"]), "manifest": str(job / "manifest.json")}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# None: honour HTTP_PROXY/HTTPS_PROXY from the environment. {}: --no-proxy was requested.
PROXY_OVERRIDE = None


def http_opener():
    handlers = [NoRedirect()]
    if PROXY_OVERRIDE is not None:
        # Passing an empty mapping makes build_opener drop proxy handling altogether, which is the
        # supported way to force a direct connection for hosts a local proxy keeps resetting.
        handlers.append(urllib.request.ProxyHandler(PROXY_OVERRIDE))
    return urllib.request.build_opener(*handlers)


def safe_url(url):
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443)
            or not any(host == suffix or host.endswith("." + suffix) for suffix in HOSTS)):
        raise ValueError("Unverified cloud URL; review official API before changing allowed hosts")
    return url


def request(url, method="GET", data=None, headers=None):
    safe_url(url)
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        return http_opener().open(req, timeout=30)
    except urllib.error.HTTPError as error:
        # Never expose bodies, signed URLs or authentication headers. The host is safe to name and
        # is what tells an API rejection (mineru.net) apart from a rejected signed upload
        # (mineru.oss-*.aliyuncs.com), which has different causes.
        host = urllib.parse.urlsplit(url).hostname or "cloud"
        raise RuntimeError(f"HTTP {error.code} from {host}; stop and inspect credentials, quota or rate limit") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RuntimeError("Cloud transport failed; preserve task state and do not blindly resubmit"
                           " (a local HTTP proxy is the usual cause; retry with --no-proxy)") from None


def api(path, token, payload=None):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    with request(API + path, method="POST" if payload is not None else "GET",
                 data=json.dumps(payload).encode() if payload is not None else None, headers=headers) as response:
        content = response.read(4_000_001)
    if len(content) > 4_000_000:
        raise ValueError("API response exceeds limit")
    body = json.loads(content)
    if body.get("code") != 0:
        # The API envelope's code/msg are protocol status fields, not credentials or signed URLs;
        # naming them is what makes quota, token and rate-limit failures distinguishable.
        message = str(body.get("msg", ""))[:200]
        raise RuntimeError(f"MinerU rejected the request (code={body.get('code')}, msg={message!r});"
                           " check quota, Token and rate limit before retrying")
    return body["data"]


def get_chunk(data, part):
    for chunk in data["chunks"]:
        if chunk["id"] == part:
            return chunk
    raise ValueError("Unknown chunk ID")


def token_value():
    value = os.environ.get("MINERU_TOKEN", "").strip()
    if not value or any(c in value for c in "\r\n"):
        raise ValueError("Configure MINERU_TOKEN with secure local input; never paste it into chat")
    return value


def submit(manifest, part, allow_upload=False, model="vlm", replace_batch=False):
    if not allow_upload:
        raise ValueError("Explicit file-scope upload consent is required (--allow-upload)")
    with locked(manifest):
        data = load(manifest)
        chunk = get_chunk(data, part)
        if chunk.get("batch_id"):
            if not replace_batch:
                return {"status": "already_submitted", "chunk": part, "next": "collect"}
            if chunk["state"] != "upload_unknown":
                if chunk["state"] == "submitted":
                    raise ValueError("Chunk was already uploaded; refusing to create a duplicate task")
                raise ValueError("Refusing to replace a batch in state " + repr(chunk["state"])
                                 + "; only an upload that never completed can be replaced")
            # A batch that never received its file stays "waiting-file" forever and cannot be reused
            # (its signed URL is not persisted). Keep the record instead of erasing it.
            chunk.setdefault("abandoned_batches", []).append(
                {"batch_id": chunk["batch_id"], "state": chunk["state"],
                 "reason": "replaced after an upload that never completed"})
            chunk["batch_id"] = None
            chunk["state"] = "prepared"
        if chunk["state"] != "prepared":
            raise ValueError("Submission result unknown; review before creating another task")
        token = token_value()
        chunk["state"] = "submission_unknown"
        save(manifest, data)
        result = api("/file-urls/batch", token, {"files": [{"name": Path(chunk["file"]).name,
                     "data_id": part, "is_ocr": True}], "model_version": model,
                     "enable_table": True, "enable_formula": True, "language": "ch"})
        if not isinstance(result.get("batch_id"), str) or not result["batch_id"] or len(result.get("file_urls", [])) != 1:
            raise ValueError("Unexpected submission response; preserve uncertain state")
        chunk.update(batch_id=result["batch_id"], state="upload_unknown")
        save(manifest, data)
        source = inside(manifest.parent, chunk["file"])
        # File objects are streamed by urllib/http.client; never attach API headers to storage.
        # Content-Type must be explicitly empty: urllib would otherwise inject
        # 'application/x-www-form-urlencoded', OSS folds that header into the signature string and
        # answers 403 SignatureDoesNotMatch for a URL that was signed without it.
        with source.open("rb") as stream, request(result["file_urls"][0], method="PUT", data=stream,
                                                 headers={"Content-Length": str(source.stat().st_size),
                                                          "Content-Type": ""}) as response:
            if response.status not in (200, 201, 204):
                raise RuntimeError("Upload not acknowledged; query existing task first")
        chunk["state"] = "submitted"
        save(manifest, data)
        return {"status": "submitted", "chunk": part, "next": "collect"}


def collect(manifest, part):
    with locked(manifest):
        data = load(manifest)
        chunk = get_chunk(data, part)
        if chunk["state"] == "done":
            target = inside(manifest.parent, chunk["zip"])
            if not target.is_file() or sha(target) != chunk["zip_sha256"]:
                raise ValueError("Saved result missing or changed")
            return {"status": "done", "chunk": part, "cached": True}
        if not chunk.get("batch_id"):
            raise ValueError("No known task; do not invent a task ID")
        batch = urllib.parse.quote(chunk["batch_id"], safe="")
        result = api(f"/extract-results/batch/{batch}", token_value())
        matches = [row for row in result["extract_result"] if row.get("data_id") == part]
        if len(matches) != 1:
            raise ValueError("Result cannot be uniquely matched to chunk")
        row = matches[0]
        chunk["state"] = "download_pending" if row["state"] == "done" else row["state"]
        save(manifest, data)
        if row["state"] != "done":
            return {"status": row["state"], "chunk": part, "next": "review failure" if row["state"] == "failed" else "collect later"}
        relative = f"results/{part}.zip"
        target = inside(manifest.parent, relative)
        temporary = target.with_suffix(".download")
        try:
            with request(row["full_zip_url"]) as response, temporary.open("wb") as stream:
                total = 0
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > 2_000_000_000:
                        raise ValueError("Result ZIP exceeds download budget")
                    stream.write(block)
            with zipfile.ZipFile(temporary) as archive:
                if archive.testzip() is not None:
                    raise ValueError("Corrupt result ZIP")
            temporary.replace(target)
        except Exception:
            # 'done' means cloud done, not locally delivered; allow collect to retry download.
            chunk["state"] = "download_pending"
            save(manifest, data)
            raise
        chunk.update(state="done", zip=relative, zip_sha256=sha(target))
        save(manifest, data)
        return {"status": "done", "chunk": part}


def safe_member(name):
    path = PurePosixPath(name)
    if not name or "\\" in name or ":" in name or path.is_absolute() or ".." in path.parts:
        raise ValueError("Unsafe ZIP path")
    if path.as_posix() != name.rstrip("/") or any(
            part.endswith((".", " ")) or re.search(r'[<>"|?*]', part)
            or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part)
            for part in path.parts):
        raise ValueError("Ambiguous or platform-unsafe ZIP path")
    return path.as_posix()


INLINE = re.compile(r"(!?\[[^\]\n]*\]\(\s*)(<[^>\n]+>|[^\s()]+(?:\([^()\n]*\)[^\s()]*)*)([ \t]+[^\n)]*)?(\))")
REFERENCE = re.compile(r"(?m)^( {0,3}\[[^\]\n]+\]:[ \t]*)(<[^>\n]+>|\S+)")
HTML_LINK = re.compile(r'''(?i)(\b(?:src|href)\s*=\s*)(["'])(.*?)(\2)''')


def rewrite_markdown(text, md_path, names, part):
    references, remote = [], []

    def target(value):
        angle = value.startswith("<") and value.endswith(">")
        raw = value[1:-1] if angle else value
        parsed = urllib.parse.urlsplit(raw)
        if parsed.scheme or raw.startswith("//"):
            if parsed.scheme.lower() not in ("http", "https", "data", "mailto") and not raw.startswith("//"):
                raise ValueError("Unsupported external link scheme")
            remote.append(raw)
            return value
        if not parsed.path:
            return value
        decoded = urllib.parse.unquote(parsed.path)
        member = posixpath.normpath(posixpath.join(posixpath.dirname(md_path), decoded))
        safe_member(member)
        if member not in names:
            raise ValueError("Missing local Markdown/image reference")
        destination = f"assets/{part}/{member}"
        references.append(destination)
        encoded = urllib.parse.quote(destination, safe="/._-~")
        if parsed.query:
            encoded += "?" + parsed.query
        if parsed.fragment:
            encoded += "#" + parsed.fragment
        return "<" + encoded + ">" if angle else encoded

    # Do not rewrite syntax samples inside fenced code blocks.
    lines, fence = [], None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            run = marker[1]
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = None
            lines.append(line)
            continue
        if fence is None:
            line = INLINE.sub(lambda m: m[1] + target(m[2]) + (m[3] or "") + m[4], line)
            line = REFERENCE.sub(lambda m: m[1] + target(m[2]), line)
            line = HTML_LINK.sub(lambda m: m[1] + m[2] + target(m[3]) + m[4], line)
        lines.append(line)
    return "".join(lines), references, len(remote)


def merge(manifest, output):
    data = load(manifest)
    if any(chunk["state"] != "done" for chunk in data["chunks"]):
        raise ValueError("All chunks must succeed before complete output can be delivered")
    output = output.resolve()
    if output.exists():
        raise ValueError("Output directory already exists; choose a new path")
    if manifest.resolve().is_relative_to(output):
        raise ValueError("Output cannot contain the job")
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"source_name": data["source_name"], "source_sha256": data["source_sha256"], "pages": data["pages"],
              "status": "complete", "checks": ["continuous_source_ranges", "result_hashes", "safe_zip_paths", "local_links"],
              "requires_review": ["OCR accuracy", "chunk boundaries", "cross-page tables", "footnotes and anchors"],
              "chunks": [], "remote_references": 0}
    documents, references = [], []
    with tempfile.TemporaryDirectory(prefix=".memo-merge-", dir=output.parent) as temporary:
        staging = Path(temporary) / "deliverable"
        staging.mkdir()
        for chunk in data["chunks"]:
            result = inside(manifest.parent, chunk["zip"])
            if sha(result) != chunk["zip_sha256"]:
                raise ValueError("Result ZIP hash mismatch")
            with zipfile.ZipFile(result) as archive:
                infos = archive.infolist()
                if len(infos) > 100_000 or sum(item.file_size for item in infos) > 4_000_000_000:
                    raise ValueError("ZIP exceeds unpack budget")
                names, canonical = set(), set()
                for info in infos:
                    name = safe_member(info.filename)
                    key = name.casefold().rstrip("/")
                    if key in canonical or stat.S_ISLNK(info.external_attr >> 16):
                        raise ValueError("Duplicate or symlink ZIP member")
                    canonical.add(key)
                    if info.file_size > max(1, info.compress_size) * 1000:
                        raise ValueError("Suspicious ZIP compression ratio")
                    if not info.is_dir():
                        names.add(name)
                candidates = sorted(name for name in names if PurePosixPath(name).name.lower() in {"full.md", "markdown.md"})
                if not candidates:
                    candidates = sorted(name for name in names if name.lower().endswith(".md"))
                if len(candidates) != 1:
                    raise ValueError("Result must have exactly one unambiguous Markdown entry")
                md_path = candidates[0]
                text = archive.read(md_path).decode("utf-8-sig")
                if not text.strip():
                    raise ValueError("Empty OCR Markdown; review before marking complete")
                rewritten, links, remote_count = rewrite_markdown(text, md_path, names, chunk["id"])
                documents.append(f"<!-- Source pages {chunk['start']}-{chunk['end']}; {chunk['id']} -->\n\n" + rewritten.strip())
                references.extend(links)
                report["remote_references"] += remote_count
                for name in sorted(names):
                    target = inside(staging, f"assets/{chunk['id']}/{name}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(name) as source, target.open("wb") as stream:
                        shutil.copyfileobj(source, stream, length=1024 * 1024)
                report["chunks"].append({"id": chunk["id"], "start": chunk["start"], "end": chunk["end"]})
        for link in references:
            if not inside(staging, link).is_file():
                raise ValueError("Rewritten link target missing")
        (staging / "document.md").write_text("\n\n".join(documents) + "\n", encoding="utf-8")
        save(staging / "report.json", report)
        staging.rename(output)
    return {"status": "complete", "pages": data["pages"], "chunks": len(data["chunks"]), "output": str(output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    split = commands.add_parser("prepare")
    split.add_argument("source", type=Path)
    split.add_argument("job", type=Path)
    split.add_argument("--max-pages", type=int, default=150)
    split.add_argument("--max-mb", type=float, default=180)
    for action in ("submit", "collect"):
        command = commands.add_parser(action)
        command.add_argument("manifest", type=Path)
        command.add_argument("--chunk", required=True)
        command.add_argument("--no-proxy", action="store_true",
                             help="ignore HTTP_PROXY/HTTPS_PROXY for this run; needed when a local "
                                  "proxy breaks the result download")
        if action == "submit":
            command.add_argument("--allow-upload", action="store_true")
            command.add_argument("--model", choices=["vlm", "pipeline"], default="vlm")
            command.add_argument("--replace-batch", action="store_true",
                                 help="the recorded batch never received its file; keep it in "
                                      "abandoned_batches and create a new one")
    joined = commands.add_parser("merge")
    joined.add_argument("manifest", type=Path)
    joined.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        if getattr(args, "no_proxy", False):
            global PROXY_OVERRIDE
            PROXY_OVERRIDE = {}
        if args.action == "prepare":
            result = prepare(args.source, args.job, args.max_pages, args.max_mb)
        elif args.action == "submit":
            result = submit(args.manifest.resolve(), args.chunk, args.allow_upload, args.model,
                            args.replace_batch)
        elif args.action == "collect":
            result = collect(args.manifest.resolve(), args.chunk)
        else:
            result = merge(args.manifest.resolve(), args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        # Unexpected library errors can include source text, URLs or credentials.
        message = str(error) if isinstance(error, (ValueError, RuntimeError)) else "Local operation failed; inspect privately"
        print(json.dumps({"status": "error", "type": type(error).__name__, "message": message}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
