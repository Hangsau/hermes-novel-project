#!/usr/bin/env python3
"""
fetch_book.py — One-shot book fetch pipeline.

Integrates scraping + verification + bookshelf update + optional git push,
emitting a machine-readable result.json so the caller only needs to read
one file instead of orchestrating 400+ tool calls.

Usage:
    python3 scripts/fetch_book.py --book-id shui_hu_zhuan [--push] [--delay 0.3]

Output:
    reading/last_result.json  (summary for the caller to inspect)
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path("/root/hermes-novel-project")
READING_DIR = REPO_ROOT / "reading"
BOOKSHELF = READING_DIR / "bookshelf.json"
SCRIPTS_DIR = REPO_ROOT / "scripts"
RESULT_FILE = READING_DIR / "last_result.json"


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


def run(cmd: list[str], cwd: Path = REPO_ROOT, timeout: int = 600) -> tuple[int, str, str]:
    log(f"RUN {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        log(f"ERR rc={proc.returncode}")
        if proc.stderr:
            log(f"stderr: {proc.stderr[:800]}")
    return proc.returncode, proc.stdout, proc.stderr


def load_bookshelf() -> dict:
    with open(BOOKSHELF, "r", encoding="utf-8") as f:
        return json.load(f)


def save_bookshelf(data: dict):
    data["meta"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(BOOKSHELF, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def git_commit_push(book_name: str) -> bool:
    run(["git", "add", "reading/", "scripts/"])
    rc, _, _ = run(["git", "diff", "--cached", "--quiet"])
    if rc == 0:
        log("Nothing to commit")
        return True
    msg = f"auto-fetch: {book_name} @ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    rc, _, _ = run(["git", "commit", "-m", msg])
    if rc != 0:
        log("git commit failed")
        return False
    rc, out, err = run(["git", "push", "origin", "HEAD"])
    if rc != 0:
        log(f"git push failed: {err[:500]}")
        return False
    log("git push OK")
    return True


def scrape(book_name: str, total: int, out_dir: Path, delay: float) -> dict:
    scraper = SCRIPTS_DIR / "scrape-wikisource.py"
    rc, out, err = run([
        sys.executable, str(scraper),
        "--book", book_name,
        "--chapters", str(total),
        "--output", str(out_dir),
        "--delay", str(delay),
    ], timeout=1200)

    success = 0
    failed_chapters = []
    for line in out.splitlines():
        if line.startswith("Ch ") and ":" in line:
            if "OK" in line:
                success += 1
            elif "FAILED" in line:
                try:
                    ch = int(line.split(":")[0].replace("Ch ", "").strip())
                    failed_chapters.append(ch)
                except ValueError:
                    pass
        if "Done:" in line and "/" in line:
            try:
                success = int(line.split("Done:")[1].split("/")[0].strip())
            except ValueError:
                pass

    return {
        "rc": rc,
        "success": success,
        "total": total,
        "failed_chapters": failed_chapters,
        "stdout_tail": out[-2000:] if out else "",
        "stderr_tail": err[-1000:] if err else "",
    }


def verify(out_dir: Path, book_name: str) -> dict:
    verifier = SCRIPTS_DIR / "verify-wikisource-chapters.py"
    rc, out, err = run([
        sys.executable, str(verifier),
        "--dir", str(out_dir),
        "--book", book_name,
    ])

    passed = 0
    failed_files = []
    issues_map = {}
    total_chars = 0

    for line in out.splitlines():
        if line.startswith("OK"):
            passed += 1
        elif line.startswith("FAIL"):
            # FAIL ch003.txt: junk: 姊妹計劃, missing_ending
            parts = line.split(":", 1)
            if len(parts) == 2:
                fname = parts[0].replace("FAIL", "").strip()
                issue_str = parts[1].strip()
                failed_files.append(fname)
                issues_map[fname] = [i.strip() for i in issue_str.split(",")]
        elif "total chars" in line:
            # Some issues found — 100 chapters, 450,000 total chars
            try:
                total_chars = int(line.split("total chars")[0].split(",")[-1].strip().replace(",", ""))
            except ValueError:
                pass

    return {
        "rc": rc,
        "passed": passed,
        "failed_files": failed_files,
        "issues": issues_map,
        "total_chars": total_chars,
        "stdout_tail": out[-2000:] if out else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="One-shot book fetch pipeline")
    parser.add_argument("--book-id", required=True, help="Book ID from bookshelf.json")
    parser.add_argument("--push", action="store_true", help="Auto git-commit-push if successful")
    parser.add_argument("--delay", type=float, default=0.5, help="Request delay (default 0.5s)")
    args = parser.parse_args()

    started = datetime.now(timezone.utc).isoformat()
    result = {
        "book_id": args.book_id,
        "started_at": started,
        "finished_at": None,
        "fetch": {},
        "verify": {},
        "bookshelf_updated": False,
        "git_pushed": False,
        "status": "pending",
        "error": None,
    }

    data = load_bookshelf()
    queue = data.get("queue", [])
    completed = data.get("completed", [])

    book = None
    for b in queue:
        if b["id"] == args.book_id:
            book = b
            break

    if not book:
        # Check if already completed
        for b in completed:
            if b["id"] == args.book_id:
                log(f"{args.book_id} already completed")
                result["status"] = "already_completed"
                with open(RESULT_FILE, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                return 0
        log(f"Book ID {args.book_id} not found in queue")
        result["status"] = "not_found"
        result["error"] = f"{args.book_id} not in queue"
        with open(RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return 1

    book_name = book["name"]
    total = book.get("total_chapters", 0)
    log(f"=== Fetching {book_name} ({args.book_id}) ===")

    if total <= 0:
        result["status"] = "skipped"
        result["error"] = "Missing total_chapters"
        with open(RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return 1

    out_dir = READING_DIR / "by_book" / args.book_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # Mark downloading
    book["status"] = "downloading"
    book["attempts"] = book.get("attempts", 0) + 1
    save_bookshelf(data)

    # 1. Scrape
    fetch_res = scrape(book_name, total, out_dir, args.delay)
    result["fetch"] = {
        "total": fetch_res["total"],
        "success": fetch_res["success"],
        "failed_chapters": fetch_res["failed_chapters"],
    }

    if fetch_res["success"] < total * 0.9:
        err_msg = f"Only {fetch_res['success']}/{total} chapters downloaded (<90%)"
        log(err_msg)
        book["status"] = "error"
        book.setdefault("error_log", []).append({"time": datetime.now(timezone.utc).isoformat(), "message": err_msg})
        if book["attempts"] >= 3:
            queue.remove(book)
            data["stats"]["total_failed"] = data["stats"].get("total_failed", 0) + 1
        else:
            book["status"] = "pending"
        save_bookshelf(data)
        result["status"] = "fetch_failed"
        result["error"] = err_msg
        with open(RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        if args.push:
            git_commit_push(f"failed-{book_name}")
        return 1

    # 2. Verify
    verify_res = verify(out_dir, book_name)
    result["verify"] = {
        "total": verify_res.get("passed", 0) + len(verify_res.get("failed_files", [])),
        "passed": verify_res.get("passed", 0),
        "failed_files": verify_res.get("failed_files", []),
        "issues": verify_res.get("issues", {}),
        "total_chars": verify_res.get("total_chars", 0),
    }

    # Even if some chapters have issues, we consider it done if >90% passed
    total_ch = result["verify"]["total"]
    passed_ch = result["verify"]["passed"]
    if passed_ch < total_ch * 0.9:
        err_msg = f"Verification failed: only {passed_ch}/{total_ch} passed (<90%)"
        log(err_msg)
        book["status"] = "error"
        book.setdefault("error_log", []).append({"time": datetime.now(timezone.utc).isoformat(), "message": err_msg})
        if book["attempts"] >= 3:
            queue.remove(book)
            data["stats"]["total_failed"] = data["stats"].get("total_failed", 0) + 1
        else:
            book["status"] = "pending"
        save_bookshelf(data)
        result["status"] = "verify_failed"
        result["error"] = err_msg
        with open(RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        if args.push:
            git_commit_push(f"failed-{book_name}")
        return 1

    # 3. Success — move to completed
    now_str = datetime.now(timezone.utc).isoformat()
    book["status"] = "completed"
    book["downloaded_at"] = now_str
    book["verified_at"] = now_str
    queue.remove(book)
    completed.append({
        "id": book["id"],
        "name": book["name"],
        "author": book.get("author"),
        "language": book.get("language"),
        "source": book.get("source"),
        "total_chapters": book.get("total_chapters"),
        "status": "completed",
        "downloaded_at": now_str,
        "verified_at": now_str,
        "path": f"by_book/{book['id']}",
    })
    data["stats"]["total_completed"] = len(completed)
    data["stats"]["total_pending"] = len(queue)
    data["stats"]["last_fetch_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    save_bookshelf(data)
    result["bookshelf_updated"] = True
    log(f"SUCCESS: {book_name} — {fetch_res['success']}/{total} chapters, {passed_ch}/{total_ch} verified")

    # 4. Optional git push
    if args.push:
        result["git_pushed"] = git_commit_push(book_name)
    else:
        log("Skipping git push (--push not set)")

    result["status"] = "completed"
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    log(f"Result written to {RESULT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
