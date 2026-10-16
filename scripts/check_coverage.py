"""Report per-page coverage and table inventory for a job's downloaded results.

Continuous page ranges only prove which pages were sent; they do not prove that every
page came back with text. This reads each finished chunk's ``*_content_list.json`` from
``results/<part>.zip`` and lists the pages that returned nothing or almost nothing, plus
how many table blocks carried real HTML rows. Offline: reads the manifest and the ZIPs.

    python -B scripts/check_coverage.py <manifest.json> [--thin 40] [--list-empty]
"""
import argparse
import json
from pathlib import Path
import sys
import zipfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def inside(root, relative):
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()) or candidate == root.resolve():
        raise ValueError("Path escapes job root")
    return candidate


def content_list(archive):
    names = [n for n in archive.namelist() if n.endswith("_content_list.json")]
    if not names:
        return None
    # Prefer the plain content_list over the _v2 variant when both are present.
    names.sort(key=lambda n: (n.endswith("_content_list_v2.json"), len(n)))
    return json.loads(archive.read(names[0]).decode("utf-8"))


def report(manifest, thin_limit, list_empty):
    manifest = Path(manifest).resolve()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not data.get("chunks"):
        raise ValueError("Invalid manifest")
    print(f"source: {data.get('source_name')}  pages: {data.get('pages')}")
    problems = 0
    for chunk in data["chunks"]:
        label = f"{chunk['id']} (p{chunk['start']}-{chunk['end']})"
        if chunk.get("state") != "done" or not chunk.get("zip"):
            print(f"== {label}: not collected yet (state={chunk.get('state')})")
            continue
        archive_path = inside(manifest.parent, chunk["zip"])
        with zipfile.ZipFile(archive_path) as archive:
            blocks = content_list(archive)
        if blocks is None:
            print(f"== {label}: no content_list.json in the result ZIP; page coverage unknown")
            continue
        pages = chunk["end"] - chunk["start"] + 1
        per_page, tables, filled = {}, 0, 0
        for block in blocks:
            index = block.get("page_idx")
            page = per_page.setdefault(index, {"blocks": 0, "chars": 0})
            page["blocks"] += 1
            page["chars"] += len((block.get("text") or "").strip())
            if block.get("type") == "table":
                tables += 1
                if str(block.get("table_body", "")).strip():
                    filled += 1
        missing = [p for p in range(pages) if p not in per_page]
        thin = sorted((p, per_page[p]["chars"]) for p in per_page if per_page[p]["chars"] < thin_limit)
        total = sum(page["chars"] for page in per_page.values())
        print(f"== {label}: {len(blocks)} blocks, {len(per_page)}/{pages} pages with content, "
              f"{total} characters ({total // max(1, len(per_page))}/page)")
        print(f"    tables: {tables} blocks, {filled} with HTML rows, {tables - filled} empty")
        if missing:
            problems += len(missing)
            print(f"    PAGES WITH NO CONTENT: {[p + chunk['start'] for p in missing]}")
        else:
            print("    pages with no content: none")
        print(f"    pages under {thin_limit} chars: {[(p + chunk['start'], c) for p, c in thin]}")
        if list_empty and (missing or thin):
            for page in missing + [p for p, _ in thin]:
                print(f"      page {page + chunk['start']}:")
                for block in blocks:
                    if block.get("page_idx") == page:
                        print(f"        {block.get('type')}: {(block.get('text') or '')[:80]!r}")
    if problems:
        print(f"\n{problems} page(s) came back empty; review the source pages before delivering.")
        return 1
    print("\nEvery page in every collected chunk returned content.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--thin", type=int, default=40, help="flag pages below this many characters")
    parser.add_argument("--list-empty", action="store_true", help="dump the blocks of flagged pages")
    args = parser.parse_args()
    try:
        return report(args.manifest, args.thin, args.list_empty)
    except Exception as error:
        message = str(error) if isinstance(error, (ValueError, RuntimeError)) else "Coverage check failed"
        print(json.dumps({"status": "error", "type": type(error).__name__, "message": message}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
