"""Compare the rendered tables and drawer data with the saved CSVs."""
from html.parser import HTMLParser
import json

from build_all_years_ranking_html import dataset_json, build_result_cards, build_fixture_cards


class PageReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sections = {}
        self.section = None
        self.cell = None
        self.row = None
        self.json_parts = []
        self.in_json = False
        self.cards = []
        self.card = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "section":
            self.section = attrs.get("id")
            if self.section in self.sections:
                raise ValueError(f"duplicate section: {self.section}")
            self.sections[self.section] = {"rows": [], "cards": []}
        if self.section and tag == "tr":
            self.row = []
        if self.section and tag == "td":
            self.cell = []
        if self.section and tag == "article":
            self.card = []
        if tag == "script" and attrs.get("id") == "rankingData":
            self.in_json = True

    def handle_data(self, text):
        if self.cell is not None:
            self.cell.append(text)
        if self.card is not None:
            self.card.append(text)
        if self.in_json:
            self.json_parts.append(text)

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            self.row.append("".join(self.cell).strip())
            self.cell = None
        if tag == "tr" and self.section and self.row:
            self.sections[self.section]["rows"].append(self.row)
            self.row = None
        if tag == "article" and self.card is not None:
            self.sections[self.section]["cards"].append("".join(self.card))
            self.card = None
        if tag == "section":
            self.section = None
        if tag == "script":
            self.in_json = False


def check_page(page: str, datasets: dict) -> None:
    parsed = PageReader()
    parsed.feed(page)
    fields = {
        "player": ["rank", "player", "team", "goals", "match_count"],
        "team": ["rank", "team", "goals", "scorer_count", "match_count", "top_scorer"],
        "standings": ["rank", "team", "played", "wins", "draws", "losses", "goals_for", "goals_against", "goal_difference", "points"],
    }
    expected_ids = {f"sec_{key}" for key in datasets}
    if set(parsed.sections) != expected_ids:
        raise ValueError("HTML sections differ from CSV datasets")
    for key, ds in datasets.items():
        section = parsed.sections[f"sec_{key}"]
        if ds.kind in fields:
            expected = [[str(row[field]).strip() for field in fields[ds.kind]] for row in ds.rows]
            if section["rows"] != expected:
                raise ValueError(f"HTML/CSV table mismatch: {key}")
        else:
            render = build_result_cards if ds.kind == "results" else build_fixture_cards
            expected = PageReader()
            expected.feed(f'<section id="cards">{render(ds.rows)}</section>')
            if section["cards"] != expected.sections["cards"]["cards"]:
                raise ValueError(f"HTML/CSV card mismatch: {key}")
    if json.loads("".join(parsed.json_parts)) != json.loads(dataset_json(datasets)):
        raise ValueError("HTML/CSV team drawer mismatch")
