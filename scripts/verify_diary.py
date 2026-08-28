#!/usr/bin/env python3
"""
IntelX Diary Validator
Enforces strict structural and line count rules for IntelX Engineering Diaries:
- Total lines in diary/YYYY-MM-DD.md must be strictly between 51 and 99 lines (50 < total_lines < 100).
- Daily summary lines must be strictly between 16 and 29 lines (15 < summary_lines < 30).
- Voice must be active first-person ("I ...").
"""

import sys
from pathlib import Path

def verify_diary_file(filepath: Path) -> bool:
    print(f"Checking diary: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        lines = [l.rstrip("\r\n") for l in f.readlines()]
    
    total_lines = len(lines)
    print(f"  Total lines: {total_lines}")
    assert 50 < total_lines < 100, f"Total lines {total_lines} must be between 51 and 99 in {filepath.name}"

    # Extract Daily Summary bullet points
    in_summary = False
    summary_bullets = []
    for line in lines:
        if line.strip() == "## Daily Summary":
            in_summary = True
            continue
        elif line.startswith("## ") and in_summary:
            in_summary = False
            break
        if in_summary and line.strip().startswith("- "):
            summary_bullets.append(line.strip())

    summary_count = len(summary_bullets)
    print(f"  Summary bullets: {summary_count}")
    assert 15 < summary_count < 30, f"Daily summary bullets ({summary_count}) must be between 16 and 29 in {filepath.name}"

    for b in summary_bullets:
        assert b.startswith("- I "), f"Bullet must start with first-person voice '- I ': '{b}'"

    print(f"  [PASS] {filepath.name} conforms to all diary rules.")
    return True

def main():
    diary_dir = Path("diary")
    if not diary_dir.exists():
        print("No diary directory found.")
        sys.exit(1)

    diary_files = sorted(diary_dir.glob("*.md"))
    if not diary_files:
        print("No diary files found.")
        sys.exit(1)

    all_passed = True
    for f in diary_files:
        try:
            verify_diary_file(f)
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            all_passed = False

    if not all_passed:
        sys.exit(1)
    print("\nAll diary files passed validation successfully.")

if __name__ == "__main__":
    main()
