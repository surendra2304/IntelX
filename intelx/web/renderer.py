"""INTELX Safe Markdown Renderer with XSS Protection and Interactive Citations."""

import html
import re

CITATION_REGEX = re.compile(r"\[([SC]):([a-zA-Z0-9_\-]+)\]")


def render_markdown_safe(md_text: str) -> str:
    """Render markdown text safely into HTML with escaped tags and interactive citation badges."""
    if not md_text:
        return ""

    # 1. Escape all raw HTML to prevent XSS
    escaped = html.escape(md_text)

    # 2. Convert Citation Badges to Interactive Buttons
    def _badge_replace(match: re.Match) -> str:
        kind = match.group(1)
        token_id = match.group(2)
        kind_name = "source" if kind == "S" else "claim"
        return (
            f'<button type="button" class="citation-badge citation-{kind_name}" '
            f'data-type="{kind}" data-id="{token_id}" '
            f"onclick=\"openCitationDrawer('{kind}', '{token_id}')\">"
            f"[{kind}:{token_id}]</button>"
        )

    escaped = CITATION_REGEX.sub(_badge_replace, escaped)

    # 3. Line by line markdown parsing
    lines = escaped.split("\n")
    html_out = []
    in_table = False
    in_list = False

    for line in lines:
        stripped = line.strip()

        # Handle Tables
        if stripped.startswith("|") and stripped.endswith("|"):
            if not in_table:
                in_table = True
                html_out.append('<div class="table-container"><table class="evidence-table">')
            # Check for separator line
            if re.match(r"^\|(\s*:?-+:?\s*\|)+$", stripped):
                continue
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            cell_tags = "".join(f"<td>{c}</td>" for c in cells)
            html_out.append(f"<tr>{cell_tags}</tr>")
            continue
        elif in_table:
            in_table = False
            html_out.append("</table></div>")

        # Handle Unordered Lists
        if stripped.startswith("- "):
            if not in_list:
                in_list = True
                html_out.append('<ul class="report-list">')
            content = stripped[2:].strip()
            # Parse bold / italics inside list items
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
            content = re.sub(r"\*(.+?)\*", r"<em>\1</em>", content)
            content = re.sub(r"`(.+?)`", r"<code>\1</code>", content)
            html_out.append(f"<li>{content}</li>")
            continue
        elif in_list:
            in_list = False
            html_out.append("</ul>")

        # Headings
        if stripped.startswith("# "):
            html_out.append(f'<h1 class="report-h1">{stripped[2:]}</h1>')
        elif stripped.startswith("## "):
            html_out.append(f'<h2 class="report-h2">{stripped[3:]}</h2>')
        elif stripped.startswith("### "):
            html_out.append(f'<h3 class="report-h3">{stripped[4:]}</h3>')
        elif not stripped:
            html_out.append('<div class="spacer"></div>')
        else:
            # Paragraph
            para = stripped
            para = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", para)
            para = re.sub(r"\*(.+?)\*", r"<em>\1</em>", para)
            para = re.sub(r"`(.+?)`", r"<code>\1</code>", para)
            html_out.append(f'<p class="report-p">{para}</p>')

    if in_table:
        html_out.append("</table></div>")
    if in_list:
        html_out.append("</ul>")

    return "\n".join(html_out)
