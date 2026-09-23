"""
Convert policy .md files into HTML, TXT, and PDF formats.
Keeps a subset as .md. Deletes the source .md file after conversion.

Run:
    python scripts/convert_policies.py
"""

import re
from pathlib import Path

import markdown as md_lib
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from reportlab.lib.enums import TA_LEFT

POLICIES_DIR = Path(__file__).parent.parent / "data" / "policies"

# Which stem gets which target format (md = leave as-is)
FORMAT_MAP = {
    # keep as Markdown
    "remote_work_policy":               "md",
    "pto_policy":                       "md",
    "data_security_policy":             "md",
    "employee_benefits_policy":         "md",
    "workplace_conduct_policy":         "md",
    # convert to HTML
    "expense_reimbursement_policy":     "html",
    "onboarding_policy":                "html",
    "company_holidays_policy":          "html",
    "leave_of_absence_policy":          "html",
    "offboarding_policy":               "html",
    # convert to TXT
    "compensation_policy":              "txt",
    "dei_policy":                       "txt",
    "health_safety_policy":             "txt",
    "recruitment_hiring_policy":        "txt",
    "vendor_management_policy":         "txt",
    # convert to PDF
    "ai_acceptable_use_policy":         "pdf",
    "employee_privacy_policy":          "pdf",
    "equipment_asset_management_policy":"pdf",
    "learning_development_policy":      "pdf",
    "performance_management_policy":    "pdf",
}


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------

def to_html(text: str, title: str) -> str:
    body = md_lib.markdown(text, extensions=["tables", "fenced_code"])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <style>
    body {{ font-family: Arial, sans-serif; max-width: 860px; margin: 40px auto; line-height: 1.6; color: #222; }}
    h1, h2, h3 {{ color: #1a1a2e; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ccc; padding: 6px 10px; }}
    th {{ background: #f0f0f0; }}
  </style>
</head>
<body>
{body}
</body>
</html>"""


def to_txt(text: str) -> str:
    # Strip markdown syntax to produce readable plain text
    t = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)   # headings
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)                    # bold
    t = re.sub(r"\*(.+?)\*", r"\1", t)                        # italic
    t = re.sub(r"`(.+?)`", r"\1", t)                          # inline code
    t = re.sub(r"^\s*[-*+]\s+", "- ", t, flags=re.MULTILINE)  # bullets
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)            # links
    t = re.sub(r"\n{3,}", "\n\n", t)                           # excess blank lines
    return t.strip()


def _md_to_story(text: str) -> list:
    """Convert markdown text to a reportlab flowables list."""
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, spaceAfter=8)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=14, spaceAfter=6)
    h3 = ParagraphStyle("h3", parent=styles["Heading3"], fontSize=12, spaceAfter=4)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10, leading=14,
                          spaceAfter=4, wordWrap="CJK")
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=16, bulletIndent=6,
                            spaceAfter=2)

    story = []
    for raw in text.split("\n"):
        line = raw.rstrip()
        # strip inline bold/italic markers for reportlab plain text
        clean = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        clean = re.sub(r"\*(.+?)\*", r"\1", clean)
        # escape XML special chars so reportlab doesn't choke
        clean = clean.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        if line.startswith("### "):
            story.append(Paragraph(clean[4:].strip(), h3))
        elif line.startswith("## "):
            story.append(Spacer(1, 4))
            story.append(Paragraph(clean[3:].strip(), h2))
        elif line.startswith("# "):
            story.append(Spacer(1, 6))
            story.append(Paragraph(clean[2:].strip(), h1))
        elif line.startswith("- ") or line.startswith("* "):
            story.append(Paragraph(f"•&nbsp;&nbsp;{clean[2:].strip()}", bullet))
        elif line == "":
            story.append(Spacer(1, 6))
        else:
            story.append(Paragraph(clean, body))

    return story


def to_pdf(text: str, output_path: Path) -> None:
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )
    doc.build(_md_to_story(text))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    converted = {"html": 0, "txt": 0, "pdf": 0, "md": 0}

    for stem, fmt in FORMAT_MAP.items():
        src = POLICIES_DIR / f"{stem}.md"
        if not src.exists():
            print(f"  SKIP (not found): {src.name}")
            continue

        text = src.read_text(encoding="utf-8")

        if fmt == "md":
            converted["md"] += 1
            print(f"  KEEP  .md  : {src.name}")
            continue

        dst = POLICIES_DIR / f"{stem}.{fmt}"

        if fmt == "html":
            title = stem.replace("_", " ").title()
            dst.write_text(to_html(text, title), encoding="utf-8")
        elif fmt == "txt":
            dst.write_text(to_txt(text), encoding="utf-8")
        elif fmt == "pdf":
            to_pdf(text, dst)

        src.unlink()  # remove original .md
        converted[fmt] += 1
        print(f"  CONVERT → .{fmt}: {dst.name}")

    print(
        f"\nDone. md={converted['md']}  html={converted['html']}  "
        f"txt={converted['txt']}  pdf={converted['pdf']}"
    )


if __name__ == "__main__":
    main()
