#!/usr/bin/env python3
"""IntelX Diary Validator.

Enforces strict structural and line count rules for IntelX Engineering Diaries:
- Total lines in diary/YYYY-MM-DD.md must be strictly between 51 and 99 lines.
- Daily summary lines must be strictly between 16 and 29 lines.
- Voice must be active first-person ("I ...").
"""

import sys
from pathlib import Path


def verify_diary_file(filepath: Path) -> bool:
    """Verify line count and voice invariants of a daily diary file."""
    print(f"Checking diary: {filepath}")
    with open(filepath, encoding="utf-8") as file_handle:
        lines = [line.rstrip("\r\n") for line in file_handle.readlines()]

    total_lines = len(lines)
    print(f"  Total lines: {total_lines}")
    assert 50 < total_lines < 100, (
        f"Total lines {total_lines} must be between 51 and 99 in {filepath.name}"
    )

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
    assert 15 < summary_count < 30, (
        f"Daily summary bullets ({summary_count}) must be between 16 and 29 in {filepath.name}"
    )

    for bullet in summary_bullets:
        assert bullet.startswith("- I "), (
            f"Bullet must start with first-person voice '- I ': '{bullet}'"
        )

    print(f"  [PASS] {filepath.name} conforms to all diary rules.")
    return True


def main():
    """Run verification across all diary files."""
    diary_dir = Path("diary")
    if not diary_dir.exists():
        print("No diary directory found.")
        sys.exit(1)

    diary_files = sorted(diary_dir.glob("*.md"))
    if not diary_files:
        print("No diary files found.")
        sys.exit(1)

    all_passed = True
    for diary_file in diary_files:
        try:
            verify_diary_file(diary_file)
        except AssertionError as err:
            print(f"  [FAIL] {err}")
            all_passed = False

    if not all_passed:
        sys.exit(1)
    print("\nAll diary files passed validation successfully.")


if __name__ == "__main__":
    main()
