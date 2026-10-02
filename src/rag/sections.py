"""Dependency-free section extraction for numbered TXT and PDF policies."""

import re
from dataclasses import dataclass


@dataclass
class HeadingSection:
    """A contiguous section whose source page is unambiguous."""

    doc_id: str
    doc_title: str
    heading: str
    heading_level: int
    content: str
    source_file: str = ""
    page_number: int | None = None


# Restrict matches to short standalone lines so numbered procedure steps remain
# body text rather than being mistaken for policy-section headings.
NUMBERED_HEADING_RE = re.compile(r"^(\d{1,2})(?:\.(\d{1,2}))?\.?(?:\s+)([^\n]{3,90})$")


def _numbered_heading(line: str) -> tuple[int, str] | None:
    match = NUMBERED_HEADING_RE.fullmatch(line.strip())
    if not match:
        return None
    label = match.group(3).strip()
    if (not label[0].isupper() or label.endswith((".", ":", ";"))
            or re.search(r":\s+[a-z]", label)):
        return None
    level = 2 if match.group(2) else 1
    number = match.group(1) + (f".{match.group(2)}" if match.group(2) else "")
    return level, f"{number}. {label}" if level == 1 else f"{number} {label}"


def split_numbered_pages(pages: list[str], doc_id: str,
                         fallback_title: str, source_file: str,
                         pdf: bool = False) -> list[HeadingSection]:
    """Split TXT/PDF by numbered headings while retaining PDF page provenance.

    A section crossing a PDF page boundary becomes two sections with the same
    heading path but distinct page numbers. This prevents a citation from
    claiming that text on page N was found on page N-1.
    """
    first_line = next((line.strip() for page in pages for line in page.splitlines()
                       if line.strip()), fallback_title)
    doc_title = first_line if not _numbered_heading(first_line) else fallback_title
    title = doc_title if len(doc_title) <= 120 else fallback_title
    sections: list[HeadingSection] = []
    parent = ""
    child = ""
    for page_index, page in enumerate(pages, start=1):
        lines: list[str] = []
        page_number = page_index if pdf else None

        def flush() -> None:
            body = "\n".join(lines).strip()
            if body:
                section_path = " > ".join(part for part in (parent, child) if part) or title
                if pdf:
                    section_path = f"{section_path} (p. {page_index})"
                sections.append(HeadingSection(
                    doc_id, title, section_path, 2 if child else 1, body,
                    source_file=source_file, page_number=page_number,
                ))
            lines.clear()

        for line in page.splitlines():
            heading = _numbered_heading(line)
            if heading:
                flush()
                level, label = heading
                if level == 1:
                    parent, child = label, ""
                else:
                    child = label
            else:
                lines.append(line)
        flush()
    return sections
