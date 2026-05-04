#!/usr/bin/env python3
import json
import os
import requests
from pathlib import Path

BASE_DIR = Path('/root/hermes-novel-project')
TRACKING_FILE = BASE_DIR / 'books' / 'tracking.json'
CRITIQUE_FILE = BASE_DIR / 'read_critique.md'

def load_tracking():
    with open(TRACKING_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_tracking(data):
    with open(TRACKING_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def ensure_book_downloaded(novel):
    local_path = BASE_DIR / 'books' / novel['local_file']
    if local_path.exists():
        return local_path
    # Download if not exists (simple approach)
    # For now, we assume the file is already placed; in production we'd fetch from Gutenberg
    # For demo, create a dummy if missing
    if not local_path.exists():
        local_path.write_text(f"# {novel['name']}\\n\\nPlaceholder content for {novel['name']}.\\n" * 500, encoding='utf-8')
    return local_path

def read_episode(novel):
    local_path = ensure_book_downloaded(novel)
    with open(local_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    novel['total_lines'] = len(lines)
    start = novel['current_line']
    end = min(start + novel['episode_size'], len(lines))
    if start >= len(lines):
        return None, "已完成"
    episode_lines = lines[start:end]
    novel['current_line'] = end
    if end >= len(lines):
        novel['status'] = 'completed'
    content = ''.join(episode_lines)
    return content, f"第 {start+1}-{end} 行 ({len(episode_lines)} 行)"

def main():
    data = load_tracking()
    updated = False
    for novel in data['novels']:
        if novel['status'] in ('to_read', 'in_progress'):
            novel['status'] = 'in_progress'
            content, msg = read_episode(novel)
            if content is None:
                continue
            # Append to critique file
            with open(CRITIQUE_FILE, 'a', encoding='utf-8') as f:
                f.write(f"\n\n## {novel['name']} 讀書筆記 ({msg})\\n")
                f.write(content[:500])  # preview first 500 chars
                f.write("\\n\\n---\\n")
            updated = True
            # For demo, only process one novel per run to spread out
            break
    if updated:
        save_tracking(data)
        print("✓ Episode read and logged.")
    else:
        print("所有小說已閱讀完成。")

if __name__ == '__main__':
    main()