import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation import GetReports
from bot_runtime import batch_limit

OUTPUT_DIRS = (
    Path(os.environ.get("NEEDS_LOCAL_PROOF_DIR", "needs_local_proof")),
    Path(os.environ.get("DEEPWIKI_CANDIDATE_DIR", "deepwiki_candidates")),
    Path(os.environ.get("DEEPWIKI_UNKNOWN_DIR", "deepwiki_unknown")),
    Path(os.environ.get("AUDITED_DIR", "audited")),
    Path(os.environ.get("REJECTED_BY_DEEPWIKI_DIR", "rejected_by_deepwiki")),
)


def _output_files() -> set[Path]:
    files: set[Path] = set()
    for directory in OUTPUT_DIRS:
        if directory.exists():
            files.update(p for p in directory.glob("*.*") if p.is_file())
    return files


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


def _write_unknown(item: dict, reason: str) -> Path:
    out_dir = Path(os.environ.get("DEEPWIKI_UNKNOWN_DIR", "deepwiki_unknown"))
    out_dir.mkdir(parents=True, exist_ok=True)
    url = str(item.get("url") or "")
    question = str(item.get("question") or item.get("prompt") or "")
    payload = {
        "deepwiki_verdict": "unknown",
        "deepwiki_source_url": url,
        "question": question,
        "reason": reason,
        "report_generated": False,
        "source_item": item,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    target = out_dir / f"audit_unknown_{_stable_id(url + question + reason)}.json"
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved explicit DeepWiki UNKNOWN fallback to {target}: {reason}")
    return target


def get_automation_pending() -> list[dict]:
    """Get pending automation records from automation_pending JSON files."""
    automation_pending_dir = Path(os.environ.get("AUTOMATION_PENDING_DIR", "automation_pending"))
    items: list[dict] = []

    if not automation_pending_dir.exists():
        print(f"Directory {automation_pending_dir} does not exist")
        return items

    json_files = sorted(automation_pending_dir.glob("*.json"))
    if not json_files:
        print(f"No JSON files found in {automation_pending_dir}")
        return items

    for json_file in json_files:
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("url"):
                        item = dict(item)
                        item["_source_file"] = str(json_file)
                        items.append(item)
            elif isinstance(data, dict) and data.get("url"):
                data = dict(data)
                data["_source_file"] = str(json_file)
                items.append(data)
        except json.JSONDecodeError as e:
            print(f"Error parsing {json_file}: {e}")
        except Exception as e:
            print(f"Error processing {json_file}: {e}")

    deduped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (str(item.get("url") or ""), str(item.get("question") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def move_files_back_to_automation() -> list[str]:
    automation_dir = Path(os.environ.get("AUTOMATION_DIR", "automation"))
    automation_pending_dir = Path(os.environ.get("AUTOMATION_PENDING_DIR", "automation_pending"))
    moved_files: list[str] = []

    automation_dir.mkdir(parents=True, exist_ok=True)
    automation_pending_dir.mkdir(parents=True, exist_ok=True)

    for file_path in sorted(automation_pending_dir.glob("*")):
        if not file_path.is_file():
            continue
        dest_path = automation_dir / file_path.name
        if dest_path.exists():
            dest_path = automation_dir / f"{file_path.stem}_{int(time.time())}{file_path.suffix}"
        shutil.move(str(file_path), str(dest_path))
        moved_files.append(str(dest_path))

    if moved_files:
        print(f"Moved {len(moved_files)} files back to {automation_dir}")
    return moved_files


def main() -> int:
    pending_items = get_automation_pending()
    total = len(pending_items)

    if total == 0:
        print("No pending reports to generate")
        return 0

    print(f"Found {total} automation records needing reports")
    max_reports = batch_limit(500)
    produced = 0
    failures: list[str] = []

    report = GetReports(teardown=True)
    try:
        for i, item in enumerate(pending_items[:max_reports], 1):
            url = str(item.get("url") or "")
            print(f"[{i}/{total}] Generating report for: {url[:80]}...")
            before = _output_files()
            try:
                result = report.get_report(url)
            except Exception as e:
                result = None
                failures.append(f"{url}: {type(e).__name__}: {e}")
                print(f"FAILED {url}: {type(e).__name__}: {e}")

            after = _output_files()
            new_files = after - before
            if result or new_files:
                produced += max(1, len(new_files))
                continue

            _write_unknown(item, "DeepWiki report UI unavailable or produced no copyable response")
            produced += 1

        print(f"\n=== Completed {min(total, max_reports)} report attempts; produced {produced} output item(s) ===")
        if failures:
            print("Failures captured as explicit unknown outputs:")
            for failure in failures[:20]:
                print(f"- {failure}")
        if produced == 0:
            move_files_back_to_automation()
            raise RuntimeError("Workflow 5 produced zero output items")
        return 0
    finally:
        try:
            if getattr(report, "teardown", False):
                report.driver.quit()
        except Exception:
            pass


if __name__ == '__main__':
    raise SystemExit(main())
