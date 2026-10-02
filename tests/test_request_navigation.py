"""Keep Chat and My Requests in one page, with the shared renderer loaded first."""

from html.parser import HTMLParser
from pathlib import Path


INDEX = Path(__file__).parents[1] / "src" / "app" / "static" / "index.html"


class ElementCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def test_requests_navigation_stays_on_home_page():
    parser = ElementCollector()
    parser.feed(INDEX.read_text(encoding="utf-8"))
    by_id = {attrs["id"]: (tag, attrs) for tag, attrs in parser.elements if "id" in attrs}
    assert by_id["nav-requests"][0] == "button"
    assert by_id["nav-requests"][1]["aria-controls"] == "requests-panel"
    assert by_id["requests-panel"][0] == "main"
    assert "hidden" in by_id["requests-panel"][1]
    assert by_id["thread"][0] == "main"
    scripts = [attrs.get("src") for tag, attrs in parser.elements if tag == "script"]
    assert scripts.index("/static/portal.js") < scripts.index("/static/app.js")


def test_ticket_confirmation_offers_an_explicit_decline():
    parser = ElementCollector()
    parser.feed(INDEX.read_text(encoding="utf-8"))
    classes = [attrs.get("class", "") for _, attrs in parser.elements]
    assert "confirmation-actions" in classes
    assert "confirm-btn" in classes
    assert "decline-btn" in classes
    assert "confirmation-declined" in classes
