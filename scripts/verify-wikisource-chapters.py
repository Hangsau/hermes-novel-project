#!/usr/bin/env python3
"""
verify-wikisource-chapters.py
驗證維基文庫抓取結果的質量。

用法：
    python3 verify-wikisource-chapters.py --dir ~/reading/by_book/西遊記 [--book "西遊記"]

檢查項目：
1. 無導航/元資料殘留（姊妹計劃、資料項、檢索自...等）
2. 有結尾語（且聽下回分解 / 書至此終）
3. 長度合理（不短於 500 chars）
4. 章節標題未被偷吃（第一行不是"詩曰"直接開頭）
"""

import argparse
import os
import sys


NAV_KEYWORDS = ["姊妹計劃", "資料項", "姊妹計划", "數据項", "检索自", "wikipedia", "wikisource"]
ENDING_KEYWORDS = ["且聽下回分解", "且聽下分解", "且聽下文分解", "至此終"]
SUSPICIOUS_STARTS = ["詩曰", "話表", "卻說", "蓛聞"]


def verify_chapter(path: str, book: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    lines = content.split("\n")
    first_line = lines[0].strip() if lines else ""

    issues = []

    # 1. Junk check
    for kw in NAV_KEYWORDS:
        if kw in content:
            issues.append(f"junk: {kw}")
            break

    # 2. Ending check
    has_ending = any(kw in content for kw in ENDING_KEYWORDS)
    if not has_ending:
        issues.append("missing_ending")

    # 3. Length check
    if len(content) < 500:
        issues.append(f"too_short ({len(content)} chars)")

    # 4. Title eaten check (first line shouldn't start with poem/narrative directly)
    #    This is a heuristic — some chapters legitimately start with "詩曰"
    #    but if combined with other issues, it's suspicious.
    if any(first_line.startswith(s) for s in SUSPICIOUS_STARTS):
        issues.append("possible_missing_title")

    return {
        "file": os.path.basename(path),
        "chars": len(content),
        "lines": len(lines),
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify scraped Wikisource chapters")
    parser.add_argument("--dir", required=True, help="Directory containing chNNN.txt files")
    parser.add_argument("--book", default="", help="Book name for ending keyword check")
    args = parser.parse_args()

    ch_dir = os.path.expanduser(args.dir)
    if not os.path.isdir(ch_dir):
        print(f"Error: not a directory: {ch_dir}", file=sys.stderr)
        return 1

    files = sorted(f for f in os.listdir(ch_dir) if f.startswith("ch") and f.endswith(".txt"))
    if not files:
        print("No chNNN.txt files found.", file=sys.stderr)
        return 1

    all_ok = True
    total_chars = 0

    for f in files:
        path = os.path.join(ch_dir, f)
        result = verify_chapter(path, args.book)
        total_chars += result["chars"]
        if result["issues"]:
            all_ok = False
            print(f"FAIL {result['file']}: {', '.join(result['issues'])}")
        else:
            print(f"OK   {result['file']}: {result['lines']} lines, {result['chars']} chars")

    print(f"\n{'All passed' if all_ok else 'Some issues found'} — {len(files)} chapters, {total_chars:,} total chars")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
