#!/usr/bin/env python3
"""
scrape-wikisource.py
通用維基文庫（zh.wikisource.org）中文古典小說章節爬蟲。

支援「第XXX回」章節命名的中文古典文學作品，
如《西遊記》《紅樓夢》《水滸傳》等。

用法：
    python3 scrape-wikisource.py --book "西遊記" --chapters 100 --output ~/reading/by_book/西遊記
"""

import argparse
import os
import re
import sys
import time
import urllib.parse
import urllib.request


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def num_to_cn(n: int) -> str:
    """將阿拉伯數字轉換為繁體中文數字表示。"""
    units = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
    tens = [
        "", "十", "二十", "三十", "四十", "五十",
        "六十", "七十", "八十", "九十",
    ]
    if n == 100:
        return "一百"
    if n > 100:
        r = n - 100
        if r < 10:
            return f"一百零{units[r]}"
        elif r == 10:
            return "一百一十"
        elif r < 20:
            return f"一百一十{units[r - 10]}"
        elif r % 10 == 0:
            return f"一百{tens[r // 10]}"
        else:
            return f"一百{tens[r // 10]}{units[r % 10]}"
    if n <= 9:
        return units[n]
    if n == 10:
        return "十"
    if n < 20:
        return "十" + units[n - 10]
    if n % 10 == 0:
        return tens[n // 10]
    return tens[n // 10] + units[n % 10]


def fetch_chapter(book: str, n: int) -> str | None:
    """爬取單一章節，回傳清洗後的純文字。"""
    url = f"https://zh.wikisource.org/wiki/{urllib.parse.quote(book)}/{urllib.parse.quote(f'第{n:03d}回')}"
    req = urllib.request.Request(url, headers=HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8")
    except Exception as exc:
        print(f"  Ch {n}: fetch failed — {exc}", file=sys.stderr)
        return None

    # 定位 mw-parser-output
    m = re.search(r'<div class="[^"]*mw-parser-output[^"]*"[^>]*>', html)
    if not m:
        print(f"  Ch {n}: mw-parser-output not found", file=sys.stderr)
        return None
    start = m.end()

    # 截斷尾部元件
    end_markers = [
        '<div class="mw-normal-catlinks">',
        '<div id="catlinks"',
        '<table class="noprint',
        '<div class="printfooter">',
        '<div class="mw-cite-backlink">',
    ]
    end = len(html)
    for marker in end_markers:
        pos = html.find(marker, start)
        if pos != -1 and pos < end:
            end = pos

    content = html[start:end]
    text = re.sub(r"<[^>]+>", "", content)
    text = re.sub(r"\[編輯\]", "", text)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    # 尋找章節標題行
    cn = num_to_cn(n)
    start_idx = 0
    for i, line in enumerate(lines):
        if f"{book}第{cn}回" in line:
            start_idx = i + 1
            break

    # 跳過導航/元資料行
    while start_idx < len(lines):
        line = lines[start_idx]
        nav_keywords = ["←", "→", "姊妹計劃", "資料項", "姊妹计划", "数据项"]
        if any(k in line for k in nav_keywords):
            start_idx += 1
            continue
        if len(line) < 25 and ("回" in line or "←" in line or "→" in line):
            start_idx += 1
            continue
        if len(line) >= 10 or line.startswith("詩曰") or line.startswith("蓋聞") or line.startswith("話表") or line.startswith("卻說"):
            break
        start_idx += 1

    # 尋找結尾（含變體）
    end_idx = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if any(end in lines[i] for end in ["且聽下回分解", "且聽下分解", "且聽下文分解", f"《{book}》至此終"]):
            end_idx = i + 1
            break

    # 步驟 2：如果尾部仍有 HTML 殘留（如 "检索自..."），再次向前回退
    while end_idx > 0 and lines[end_idx - 1].startswith("检索自"):
        end_idx -= 1

    return "\n".join(lines[start_idx:end_idx])


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape classical Chinese novels from Wikisource")
    parser.add_argument("--book", required=True, help="Book name as used on zh.wikisource.org (e.g. 西遊記)")
    parser.add_argument("--chapters", type=int, required=True, help="Total number of chapters")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--delay", type=float, default=0.3, help="Seconds between requests (default: 0.3)")
    args = parser.parse_args()

    out_dir = os.path.expanduser(args.output)
    os.makedirs(out_dir, exist_ok=True)

    success = 0
    failed: list[int] = []

    for n in range(1, args.chapters + 1):
        text = fetch_chapter(args.book, n)
        if text and len(text) > 100:
            path = os.path.join(out_dir, f"ch{n:03d}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            success += 1
            print(f"Ch {n}: OK ({len(text.splitlines())} lines)")
        else:
            failed.append(n)
            print(f"Ch {n}: FAILED")
        time.sleep(args.delay)

    # 合併全文
    full_path = os.path.join(out_dir, f"{args.book}_全文.txt")
    with open(full_path, "w", encoding="utf-8") as outf:
        for n in range(1, args.chapters + 1):
            ch_path = os.path.join(out_dir, f"ch{n:03d}.txt")
            if os.path.exists(ch_path):
                with open(ch_path, "r", encoding="utf-8") as inf:
                    outf.write(inf.read())
                    outf.write("\n\n")

    print(f"\nDone: {success}/{args.chapters} chapters downloaded.")
    if failed:
        print(f"Failed chapters: {failed}")
    print(f"Full text: {full_path}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
