"""What a visitor can read in an HTML page. Comments, scripts and styles are dropped."""
from html.parser import HTMLParser


class _Reader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.items, self._hidden, self._item = [], [], 0, None

    def handle_starttag(self, tag, attrs):
        self._hidden += tag in ("script", "style")
        if tag == "li":
            self._item = []

    def handle_endtag(self, tag):
        self._hidden = max(0, self._hidden - (tag in ("script", "style")))
        if tag == "li" and self._item is not None:
            self.items.append(" ".join(" ".join(self._item).split()))
            self._item = None

    def handle_data(self, data):
        if not self._hidden:
            self.parts.append(data)
            if self._item is not None:
                self._item.append(data)


def _read(html: str) -> _Reader:
    reader = _Reader()
    reader.feed(html)
    return reader


def visible_text(html: str) -> str:
    return " ".join(" ".join(_read(html).parts).split())


def list_items(html: str) -> list[str]:
    """Text of each <li>. A notice itemises the data it collects in a list (Rule 3)."""
    return _read(html).items
