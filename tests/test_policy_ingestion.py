"""Citation-provenance regression checks for numbered TXT/PDF sources."""

from src.rag.sections import _numbered_heading, split_numbered_pages


def test_numbered_heading_does_not_split_procedure_steps() -> None:
    assert _numbered_heading("2.1 Approved Tools List") == (2, "2.1 Approved Tools List")
    assert _numbered_heading("3. Data Input Rules") == (1, "3. Data Input Rules")
    assert _numbered_heading("1. Employee submits a detailed request to their manager.") is None
    assert _numbered_heading("2. Manager: check the request") is None


def test_txt_uses_section_breadcrumb_and_source_filename() -> None:
    sections = split_numbered_pages(
        ["Example Policy\nDocument ID: POL-TEST-001\n\n1. Scope\nApplies to everyone.\n"
         "2. Rules\n2.1 Exceptions\nAsk HR first."],
        "POL-TEST-001", "Fallback", "example_policy.txt",
    )
    exception = next(s for s in sections if "Ask HR first" in s.content)
    assert exception.heading == "2. Rules > 2.1 Exceptions"
    assert exception.doc_title == "Example Policy"
    assert exception.source_file == "example_policy.txt"
    assert exception.page_number is None


def test_pdf_continuation_retains_heading_but_changes_page() -> None:
    sections = split_numbered_pages(
        ["Example Policy\n1. Scope\nFirst-page rule.",
         "Continued rule.\n2. Exceptions\nSecond-page exception."],
        "POL-TEST-001", "Fallback", "example_policy.pdf", pdf=True,
    )
    first = next(s for s in sections if "First-page rule" in s.content)
    continued = next(s for s in sections if "Continued rule" in s.content)
    exception = next(s for s in sections if "Second-page exception" in s.content)
    assert (first.heading, first.page_number) == ("1. Scope (p. 1)", 1)
    assert (continued.heading, continued.page_number) == ("1. Scope (p. 2)", 2)
    assert (exception.heading, exception.page_number) == ("2. Exceptions (p. 2)", 2)
    assert all(s.source_file == "example_policy.pdf" for s in sections)
