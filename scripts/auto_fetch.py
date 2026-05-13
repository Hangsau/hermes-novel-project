#!/usr/bin/env python3
"""
Daily auto-fetch script for classical Chinese novels from Wikisource.
Reads bookshelf.json, picks the next pending book, fetches it, verifies,
updates the JSON, commits and pushes to GitHub.
"""

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


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line, flush=True)


def run(cmd: list[str], cwd: Path = REPO_ROOT, timeout: int = 300) -> tuple[int, str, str]:
    log(f"RUN {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        log(f"ERR rc={proc.returncode} stdout={proc.stdout[:500]} stderr={proc.stderr[:500]}")
    return proc.returncode, proc.stdout, proc.stderr


def load_bookshelf() -> dict:
    with open(BOOKSHELF, "r", encoding="utf-8") as f:
        return json.load(f)


def save_bookshelf(data: dict):
    data["meta"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(BOOKSHELF, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def git_commit_push(book_name: str) -> bool:
    # stage only reading/ and scripts/
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


def fetch_book(book: dict) -> tuple[bool, str]:
    book_id = book["id"]
    book_name = book["name"]
    total = book.get("total_chapters", 0)
    lang = book.get("language", "zh-classical")

    if total <= 0:
        return False, "Missing total_chapters"

    out_dir = READING_DIR / "by_book" / book_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # Run scraper
    scraper = SCRIPTS_DIR / "scrape-wikisource.py"
    cmd = [
        sys.executable, str(scraper),
        "--book", book_name,
        "--chapters", str(total),
        "--output", str(out_dir),
        "--delay", "1.0",
    ]
    wiki_name = book.get("wiki_name")
    if wiki_name:
        cmd += ["--wiki-name", wiki_name]
    rc, out, err = run(cmd)
    if rc != 0:
        return False, f"scraper failed: {err[:500]}"

    # Parse scraper output for success count
    success = 0
    for line in out.splitlines():
        if "Done:" in line and "/" in line:
            try:
                success = int(line.split("Done:")[1].split("/")[0].strip())
            except ValueError:
                pass

    if success < total * 0.9:
        return False, f"Only {success}/{total} chapters downloaded (<90%)"

    # Verify
    verifier = SCRIPTS_DIR / "verify-wikisource-chapters.py"
    rc, out, err = run([
        sys.executable, str(verifier),
        "--dir", str(out_dir),
        "--book", book_name,
    ])
    if rc != 0:
        return False, f"verifier found issues: {err[:500]}"

    return True, f"Fetched {success}/{total} chapters, verification passed"


def main():
    log("=== Daily auto-fetch started ===")

    data = load_bookshelf()
    queue = data.get("queue", [])
    completed = data.get("completed", [])

    # Pick next pending book (attempts < 3) — include 'downloading' to resume interrupted runs
    candidate = None
    for b in queue:
        if b.get("status") in ("pending", "downloading") and b.get("attempts", 0) < 3:
            candidate = b
            break

    if candidate is None:
        log("No pending books available")
        # Still try to push any local changes
        git_commit_push("no-op")
        return 0

    book_id = candidate["id"]
    book_name = candidate["name"]
    log(f"Selected: {book_name} ({book_id})")

    # Mark as downloading
    candidate["status"] = "downloading"
    candidate["attempts"] = candidate.get("attempts", 0) + 1
    save_bookshelf(data)

    ok, msg = fetch_book(candidate)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    if ok:
        candidate["status"] = "downloaded"
        candidate["downloaded_at"] = now_str
        candidate["verified_at"] = now_str
        # Move to completed
        queue.remove(candidate)
        completed.append({
            "id": candidate["id"],
            "name": candidate["name"],
            "author": candidate.get("author"),
            "language": candidate.get("language"),
            "source": candidate.get("source"),
            "total_chapters": candidate.get("total_chapters"),
            "status": "completed",
            "downloaded_at": candidate["downloaded_at"],
            "verified_at": candidate["verified_at"],
            "path": f"by_book/{candidate['id']}",
        })
        data["stats"]["total_completed"] = len(completed)
        data["stats"]["total_pending"] = len(queue)
        data["stats"]["last_fetch_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        save_bookshelf(data)
        git_commit_push(book_name)
        log(f"SUCCESS: {book_name} — {msg}")
        return 0
    else:
        candidate["status"] = "error"
        candidate.setdefault("error_log", []).append({
            "time": now_str,
            "message": msg,
        })
        # If attempts >= 3, keep as error; else back to pending
        if candidate["attempts"] >= 3:
            log(f"PERMANENT FAIL: {book_name} after 3 attempts — {msg}")
            data["stats"]["total_failed"] = data["stats"].get("total_failed", 0) + 1
        else:
            candidate["status"] = "pending"
            log(f"RETRY LATER: {book_name} — {msg}")
        save_bookshelf(data)
        git_commit_push(f"failed-{book_name}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
