"""Minimal stdlib HTML -> (blocks) converter for SEC exhibits.

Output: a list of blocks in document order, each either
  ("text", str)                  for a paragraph-ish run of prose, or
  ("table", [[cell_text, ...]])  for a table (rows of cell strings, colspans expanded as blanks).
"""
import html, re
from html.parser import HTMLParser

BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "center"}


class _P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.buf = [], []
        self.tables = []          # stack of tables: list of rows
        self.row = None
        self.cell = None
        self.skip = 0

    def _flush_text(self):
        t = _norm("".join(self.buf))
        if t:
            self.blocks.append(("text", t))
        self.buf = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "table":
            if not self.tables:
                self._flush_text()
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self.row = []
            self.tables[-1].append(self.row)
        elif tag in ("td", "th") and self.tables:
            if self.row is None:
                self.row = []; self.tables[-1].append(self.row)
            span = dict(attrs).get("colspan") or "1"
            try:
                span = max(1, min(20, int(re.sub(r"\D", "", span) or 1)))
            except ValueError:
                span = 1
            self.cell = []
            self.row.append(self.cell)
            for _ in range(span - 1):
                self.row.append([])
        elif tag in BLOCK_TAGS:
            if self.cell is not None:
                self.cell.append(" ")
            elif not self.tables:
                self._flush_text()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag == "table" and self.tables:
            t = self.tables.pop()
            rows = [[_norm("".join(c)) for c in r] for r in t]
            rows = [r for r in rows if any(r)]
            if self.tables:          # nested table: flatten into parent cell text
                if self.cell is not None:
                    self.cell.append(" ".join(" ".join(r) for r in rows))
            elif rows:
                self.blocks.append(("table", rows))
            self.row = self.cell = None
        elif tag in ("td", "th"):
            self.cell = None
        elif tag == "tr":
            self.row = None
        elif tag in BLOCK_TAGS and not self.tables:
            self._flush_text()

    def handle_data(self, data):
        if self.skip:
            return
        if self.cell is not None:
            self.cell.append(data)
        elif not self.tables:
            self.buf.append(data)


def _norm(s):
    s = s.replace("\xa0", " ").replace("\u200b", "").replace("\u2014", "—").replace("\u2013", "–")
    return re.sub(r"\s+", " ", s).strip()


def parse(raw: bytes):
    txt = raw.decode("utf-8", "replace")
    if "<html" not in txt[:5000].lower() and "<table" not in txt.lower() and "<p" not in txt.lower():
        # plain-text exhibit (older filings): split into paragraphs
        return [("text", _norm(p)) for p in re.split(r"\n\s*\n", html.unescape(txt)) if _norm(p)]
    p = _P()
    p.feed(txt)
    p._flush_text()
    return p.blocks
