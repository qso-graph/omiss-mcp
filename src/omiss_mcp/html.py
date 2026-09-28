"""Reading omiss.net's HTML: tables, text, and scrubbing.

The pages are hand-written PHP output, not an API, so everything here is
defensive: unknown markup is skipped, and a page that no longer has the shape
a parser expects raises PageChanged rather than returning wrong data.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser


class OmissError(Exception):
    """The request couldn't be answered. The message is safe to show a user."""


class PageChanged(OmissError):
    def __init__(self, page: str) -> None:
        super().__init__(
            f"OMISS changed the layout of {page}, so omiss-mcp can't read it yet. "
            "Please report it at https://github.com/qso-graph/omiss-mcp/issues"
        )


# Email addresses are never returned, even when a page prints one.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Coordinators' mailto links are written by a script that hides the address;
# keep the callsign it prints and drop the script (and the address) whole.
_MAILTO_SCRIPT_RE = re.compile(
    r"<script[^>]*>(?:(?!</script>).)*?document\.write\('([A-Za-z0-9/]*)'\s*\+\s*'</a>'\);"
    r"(?:(?!</script>).)*?</script>",
    re.S | re.I,
)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_SPACE_RE = re.compile(r"[ \t\r\f\v\xa0]+")


def decode(body: bytes) -> str:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("latin-1")


def scrub(text: str) -> str:
    """Remove email addresses from text that will be returned."""
    return _EMAIL_RE.sub("[email removed]", text)


def clean(text: str) -> str:
    """Collapse whitespace on each line, drop empty lines, scrub."""
    lines = (_SPACE_RE.sub(" ", line).strip() for line in scrub(text).split("\n"))
    return "\n".join(line for line in lines if line)


def one_line(text: str) -> str:
    return clean(text).replace("\n", " ")


def prepare(page: str) -> str:
    """Page source with hidden addresses and comments removed."""
    page = _MAILTO_SCRIPT_RE.sub(lambda m: m.group(1), page)
    return _COMMENT_RE.sub("", page)


def text_of(fragment: str) -> str:
    """Visible text of an HTML fragment, <br> as a new line."""
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"<(script|style)\b.*?</\1>", "", fragment, flags=re.S | re.I)
    return clean(html.unescape(re.sub(r"<[^>]+>", "", fragment)))


class _Tables(HTMLParser):
    """Every table's rows, as lists of cell text. Nested tables are their own."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._stack: list[dict] = []  # open tables
        self._skip = 0  # inside script/style

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "table":
            self._stack.append({"rows": [], "row": None, "cell": None})
        elif not self._stack:
            return
        elif tag == "tr":
            self._end_row()
            self._stack[-1]["row"] = []
        elif tag in ("td", "th"):
            self._end_cell()
            t = self._stack[-1]
            if t["row"] is None:
                t["row"] = []
            t["cell"] = []
        elif tag == "br":
            self._text("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag == "br":
            self._text("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif not self._stack:
            return
        elif tag == "table":
            self._end_row()
            self.tables.append(self._stack.pop()["rows"])
        elif tag == "tr":
            self._end_row()
        elif tag in ("td", "th"):
            self._end_cell()

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._text(data)

    def _text(self, data: str) -> None:
        if self._stack and self._stack[-1]["cell"] is not None:
            self._stack[-1]["cell"].append(data)

    def _end_cell(self) -> None:
        t = self._stack[-1]
        if t["cell"] is not None:
            if t["row"] is None:
                t["row"] = []
            t["row"].append(clean("".join(t["cell"])))
            t["cell"] = None

    def _end_row(self) -> None:
        self._end_cell()
        t = self._stack[-1]
        if t["row"]:
            t["rows"].append(t["row"])
        t["row"] = None


def tables(page: str) -> list[list[list[str]]]:
    """Every table in the page, in the order they close (inner tables first)."""
    parser = _Tables()
    parser.feed(prepare(page))
    parser.close()
    return parser.tables


def find_table(page: str, header: list[str], page_name: str) -> list[list[str]]:
    """The first table whose first row starts with ``header`` (case and spacing
    ignored); its rows after the header. PageChanged if there's none."""
    want = [h.casefold() for h in header]
    for rows in tables(page):
        if rows and [one_line(c).casefold() for c in rows[0][: len(want)]] == want:
            return rows[1:]
    raise PageChanged(page_name)


def main_content(page: str) -> str:
    """The page's main content area (between its template markers), or the page."""
    m = re.search(r'InstanceBeginEditable name="MainContent" -->(.*?)<!-- InstanceEndEditable', page, re.S)
    return m.group(1) if m else page
