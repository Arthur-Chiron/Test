"""Tests hors ligne de compter_partis.py.

Les pages HTML ci-dessous imitent la sortie de l'API MediaWiki (action=parse) :
titres classiques <h2> et nouvel habillage <div class="mw-heading">, renvois
<sup class="reference">, navbox, sections « See also » / « References ».

Lancer :  python -m unittest discover -s tests -v
"""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import compter_partis as cp  # noqa: E402


INDEX_HTML = """
<div class="mw-parser-output">
<p>These are lists of American state and local politicians convicted of crimes.</p>
<ul>
  <li><a href="/wiki/List_of_Alabama_politicians_convicted_of_crimes">Alabama</a></li>
  <li><a href="/wiki/List_of_Illinois_politicians_convicted_of_crimes">Illinois</a></li>
  <li><a href="/wiki/List_of_Illinois_politicians_convicted_of_crimes#Chicago">Chicago</a></li>
  <li><a href="/wiki/List_of_Ohio_politicians_convicted_of_crimes">Ohio</a></li>
</ul>
<div class="mw-heading mw-heading2"><h2 id="See_also">See also</h2></div>
<ul>
  <li><a href="/wiki/List_of_American_federal_politicians_convicted_of_crimes">Federal</a></li>
  <li><a href="/wiki/List_of_Canadian_politicians_convicted_of_crimes">Canada</a></li>
</ul>
<div class="navbox"><ul><li><a href="/wiki/List_of_Texas_politicians_convicted_of_crimes">Texas</a> (R)</li></ul></div>
</div>
"""

# Ancien format : <h2><span class="mw-headline">...</span></h2>
ALABAMA_HTML = """
<div class="mw-parser-output">
<h2><span class="mw-headline" id="State">State officials</span></h2>
<ul>
  <li><a href="/wiki/Mike_Hubbard_(politician)">Mike Hubbard</a> (R), Speaker of the
      <a href="/wiki/Alabama_House_of_Representatives">Alabama House</a>, convicted of ethics
      violations (2016).<sup class="reference"><a href="#cite_note-1">[1]</a></sup></li>
  <li><a href="/wiki/Don_Siegelman">Don Siegelman</a> (D), Governor of Alabama, convicted of
      bribery (2006).<sup class="reference">[2]</sup></li>
  <li>Larry Langford (D-Birmingham), Mayor of Birmingham, convicted of bribery (2009).</li>
  <li>Smith, a Washington (D.C.) lobbyist, was convicted of fraud (2001).</li>
</ul>
<h3><span class="mw-headline">Local</span></h3>
<ul>
  <li>Jefferson County:
    <ul>
      <li>Chris McNair (Democrat), county commissioner, convicted of bribery (2006).</li>
      <li>Gary White (Republican Party), county commissioner, convicted of bribery (2008).</li>
    </ul>
  </li>
  <li>A Democratic city councilman of Montgomery, convicted of extortion (1999).</li>
  <li>Jim Doe, sheriff, convicted of embezzlement (1990).</li>
</ul>
<h2><span class="mw-headline" id="References">References</span></h2>
<ol class="references"><li>Some citation (R)</li></ol>
<ul><li>Fake Reference Person (D), should not be counted.</li></ul>
</div>
"""

# Nouveau format : <div class="mw-heading"><h2>...</h2></div>, plus un tableau.
ILLINOIS_HTML = """
<div class="mw-parser-output">
<div class="mw-heading mw-heading2"><h2 id="Governors">Governors</h2></div>
<table class="wikitable sortable">
  <tr><th>Name</th><th>Office</th><th>Party</th><th>Year</th></tr>
  <tr><td><a href="/wiki/Rod_Blagojevich">Rod Blagojevich</a></td><td>Governor</td><td>Democratic</td><td>2011</td></tr>
  <tr><td><a href="/wiki/George_Ryan">George Ryan</a></td><td>Governor</td><td>Republican</td><td>2006</td></tr>
  <tr><td>Otto Kerner Jr.</td><td>Governor</td><td>D</td><td>1973</td></tr>
</table>
<div class="mw-heading mw-heading2"><h2 id="Chicago">Chicago</h2></div>
<div class="mw-heading mw-heading3"><h3 id="Republicans">Republicans</h3></div>
<ul>
  <li>Bob Example, alderman, convicted of tax fraud (1980).</li>
</ul>
<div class="mw-heading mw-heading3"><h3 id="Democrats">Democrats</h3></div>
<ul>
  <li>Ed Burke (D), alderman, convicted of racketeering (2023).</li>
  <li>Jane Example, alderwoman, convicted of fraud (1990).</li>
  <li><a href="/wiki/Mike_Hubbard_(politician)">Mike Hubbard</a> (R), duplicate entry also present in another list.</li>
</ul>
<ul>
  <li>See <a href="/wiki/List_of_Cook_County_politicians_convicted_of_crimes">List of Cook County politicians convicted of crimes</a></li>
</ul>
<div class="mw-heading mw-heading2"><h2 id="See_also">See also</h2></div>
<ul><li><a href="/wiki/List_of_Indiana_politicians_convicted_of_crimes">Indiana</a></li></ul>
</div>
"""

COOK_HTML = """
<div class="mw-parser-output">
<ul>
  <li>Jim Example (DFL), commissioner, convicted (1995).</li>
  <li>Al Example (I), commissioner, convicted (1996).</li>
</ul>
</div>
"""


class FakeSource:
    def __init__(self, pages, redirects=None):
        self.pages = pages
        self.redirects = redirects or {}
        self.requested = []

    def get_html(self, title):
        self.requested.append(title)
        title = self.redirects.get(title, title)
        if title not in self.pages:
            raise cp.PageNotFound(title)
        return title, self.pages[title]


def fake_site():
    return FakeSource({
        cp.INDEX_TITLE: INDEX_HTML,
        "List of Alabama politicians convicted of crimes": ALABAMA_HTML,
        "List of Illinois politicians convicted of crimes": ILLINOIS_HTML,
        "List of Cook County politicians convicted of crimes": COOK_HTML,
        # Ohio est absente -> PageNotFound, doit être ignorée proprement.
    })


class TestMarkers(unittest.TestCase):
    def test_markers(self):
        cases = {
            "Kwame Kilpatrick (D), Mayor of Detroit": cp.DEM,
            "Joe (R), Senator": cp.REP,
            "Joe (R-TX), Senator": cp.REP,
            "Joe (D–Chicago) alderman": cp.DEM,
            "Joe (Democrat), mayor": cp.DEM,
            "Joe (Democratic), mayor": cp.DEM,
            "Joe (Republican Party), mayor": cp.REP,
            "Joe (DFL), legislator": cp.DEM,
            "Joe (Democratic–Farmer–Labor), legislator": cp.DEM,
            "Joe (I), legislator": cp.OTHER,
            "Joe (Libertarian), legislator": cp.OTHER,
            "Joe (Whig), 1850": cp.OTHER,
            "Joe (Democratic-Republican), 1810": cp.OTHER,
            "Joe ( R ), Senator": cp.REP,
            "Jospeth M Meyers (populist) convicted": cp.OTHER,
            "Freddy Valentin (PNP) was indicted": cp.OTHER,
            "José Luis Cruz Cruz (PPD) convicted": cp.OTHER,
            "Timothy Villagomez (CP) was sentenced": cp.OTHER,
            "Chuck Turner (GRP) was expelled": cp.OTHER,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(cp.find_marker(text)[0], expected)

    def test_false_positives(self):
        for text in ["Lobbyist in Washington (D.C.)", "Providence (R.I.) mayor",
                     "Rep. John Smith, convicted", "(Representative), convicted",
                     "convicted in 2001 (Dallas)", "(Dennis) Smith",
                     "Harvey D Garrison (?) convicted", "Carolyn Davis (-) was convicted",
                     "John Smith (indicted 2009)"]:
            with self.subTest(text=text):
                self.assertIsNone(cp.find_marker(text))

    def test_first_marker_wins(self):
        self.assertEqual(cp.find_marker("Joe (R, formerly D), mayor")[0], cp.REP)

    def test_cell(self):
        self.assertEqual(cp.party_from_cell("Democratic"), cp.DEM)
        self.assertEqual(cp.party_from_cell("R"), cp.REP)
        self.assertEqual(cp.party_from_cell("Republican Party"), cp.REP)
        self.assertEqual(cp.party_from_cell("Independent"), cp.OTHER)
        self.assertIsNone(cp.party_from_cell(""))


class TestParsePage(unittest.TestCase):
    def test_alabama_old_headings(self):
        entries, links = cp.parse_page(ALABAMA_HTML, "AL")
        by_name = {e.name: e for e in entries}
        self.assertEqual(by_name["Mike Hubbard"].party, cp.REP)
        self.assertEqual(by_name["Mike Hubbard"].method, cp.METHOD_MARKER)
        self.assertEqual(by_name["Don Siegelman"].party, cp.DEM)
        self.assertEqual(by_name["Larry Langford"].party, cp.DEM)
        self.assertEqual(by_name["Chris McNair"].party, cp.DEM)
        self.assertEqual(by_name["Gary White"].party, cp.REP)
        self.assertEqual(by_name["Gary White"].section, "State officials")
        self.assertEqual(by_name["Gary White"].subsection, "Local")
        # Les renvois [1] sont retirés du texte.
        self.assertNotIn("[1]", by_name["Mike Hubbard"].text)
        # « (D.C.) » n'est pas un parti ; « Democratic » en texte libre = mot-clé.
        self.assertEqual(by_name["Smith"].party, cp.UNKNOWN)
        kw = [e for e in entries if e.method == cp.METHOD_KEYWORD]
        self.assertEqual(len(kw), 1)
        self.assertEqual(kw[0].party, cp.DEM)
        self.assertEqual(by_name["Jim Doe"].party, cp.UNKNOWN)
        # L'intitulé « Jefferson County: » n'est pas une personne.
        self.assertFalse(any(e.text.startswith("Jefferson County") for e in entries))
        # Rien n'est pris dans « References ».
        self.assertFalse(any("Fake Reference" in e.text for e in entries))
        self.assertFalse(any("citation" in e.text for e in entries))
        self.assertEqual(len(entries), 8)
        self.assertEqual(links, [])

    def test_illinois_new_headings_table_and_heading_party(self):
        entries, links = cp.parse_page(ILLINOIS_HTML, "IL")
        by_name = {e.name: e for e in entries}
        self.assertEqual(by_name["Rod Blagojevich"].party, cp.DEM)
        self.assertEqual(by_name["Rod Blagojevich"].method, cp.METHOD_COLUMN)
        self.assertEqual(by_name["George Ryan"].party, cp.REP)
        self.assertEqual(by_name["Otto Kerner Jr."].party, cp.DEM)
        self.assertEqual(by_name["Bob Example"].party, cp.REP)
        self.assertEqual(by_name["Bob Example"].method, cp.METHOD_HEADING)
        self.assertEqual(by_name["Jane Example"].party, cp.DEM)
        # Un marqueur explicite l'emporte sur le titre de section.
        self.assertEqual(by_name["Mike Hubbard"].party, cp.REP)
        self.assertEqual(by_name["Ed Burke"].section, "Chicago")
        self.assertEqual(by_name["Ed Burke"].subsection, "Democrats")
        # La puce « See List of Cook County... » est un lien, pas une personne.
        self.assertFalse(any("Cook County" in e.text for e in entries))
        self.assertEqual(links, ["List of Cook County politicians convicted of crimes"])

    def test_index_links(self):
        entries, links = cp.parse_page(INDEX_HTML, cp.INDEX_TITLE)
        self.assertEqual(entries, [])
        # Ancre #Chicago fusionnée, « See also » et navbox ignorés.
        self.assertEqual(links, [
            "List of Alabama politicians convicted of crimes",
            "List of Illinois politicians convicted of crimes",
            "List of Ohio politicians convicted of crimes",
        ])


def li_entries(inner_html, section="State"):
    html = f'<div class="mw-parser-output"><h2>{section}</h2><ul>{inner_html}</ul></div>'
    return cp.parse_page(html, "P")[0]


class TestRealWorldPatterns(unittest.TestCase):
    """Formulations relevées sur les vraies listes Wikipédia par décennie."""

    def test_office_before_linked_name(self):
        [e] = li_entries('<li>State Representative <a href="/wiki/Ed_Henry_(politician)">Ed Henry</a>'
                         ' (R) convicted of fraud. (2019)</li>')
        self.assertEqual((e.name, e.article, e.party), ("Ed Henry", "Ed Henry (politician)", cp.REP))

    def test_suffix_jr_is_part_of_the_name(self):
        entries = li_entries(
            '<li>Governor Otto Kerner, Jr. (D) was convicted. (1973)</li>'
            '<li>State Senator William Lee Slocum, Jr. (R) pleaded guilty. (1990)</li>')
        self.assertEqual([e.name for e in entries],
                         ["Governor Otto Kerner, Jr.", "State Senator William Lee Slocum, Jr."])
        # Deux personnes différentes : pas de fusion sur « Jr. ».
        self.assertEqual(len(cp.deduplicate(entries)), 2)

    def test_several_people_convicted_together(self):
        entries = li_entries(
            "<li>State Senators Joseph DiCarlo (D) and Ronald MacKenzie (R) were convicted of "
            "violating the Hobbs Act. (1977)</li>"
            "<li>Governor's Councilors Joseph Ray Crimmins (D) and Raymond F. Sullivan (D) and "
            "former councilors Michael Favulli (D) and Ernest C. Stasiun (D) were found guilty "
            "of conspiracy for requesting bribes from Governor Foster Furcolo. (1965)</li>")
        self.assertEqual([(e.name, e.party) for e in entries], [
            ("State Senators Joseph DiCarlo", cp.DEM), ("Ronald MacKenzie", cp.REP),
            ("Governor's Councilors Joseph Ray Crimmins", cp.DEM), ("Raymond F. Sullivan", cp.DEM),
            ("former councilors Michael Favulli", cp.DEM), ("Ernest C. Stasiun", cp.DEM),
        ])

    def test_people_named_after_the_verb_are_not_counted(self):
        entries = li_entries(
            "<li>Tax Assessor of Putnam County Byron Looper (R), was convicted of the murder of "
            "State Senator Tommy Burks (D). (2000)</li>"
            "<li>Tax collector of Seminole County Joel Greenberg (R) was convicted of sex "
            "trafficking for former congressman Matt Gaetz (R-FL). (2022)</li>")
        self.assertEqual([(e.name, e.party) for e in entries], [
            ("Tax Assessor of Putnam County Byron Looper", cp.REP),
            ("Tax collector of Seminole County Joel Greenberg", cp.REP),
        ])

    def test_same_person_twice_in_one_item(self):
        entries = li_entries(
            "<li>Cincinnati City Councilor Jeffrey Pastor (R) convicted of fraud. (2023) "
            "* Cincinnati City Councilor Jeffrey Pastor (R) convicted of fraud. (2023)</li>")
        self.assertEqual(len(entries), 1)

    def test_detail_sub_items_are_not_extra_people(self):
        entries = li_entries(
            "<li>State Senator John McGee (R):<ul>"
            "<li>Found guilty of drunk driving and auto theft. (2013)</li>"
            "<li>Pleaded guilty to probation violation. (2015)</li></ul></li>"
            "<li>Speaker of the House Edison Misla Aldarondo (R) was convicted of extortion.<ul>"
            "<li>Jose Omar Cruz-Mercado was the Associate Secretary of Education.</li></ul></li>")
        self.assertEqual([(e.name, e.party) for e in entries], [
            ("State Senator John McGee", cp.REP),
            ("Speaker of the House Edison Misla Aldarondo", cp.REP),
            ("Jose Omar Cruz-Mercado was the Associate Secretary of Education.", cp.UNKNOWN),
        ])

    def test_unlinked_namesakes_in_different_states_are_kept(self):
        a = li_entries("<li>Mayor John Smith (D) convicted. (1990)</li>", section="Ohio")
        b = li_entries("<li>Mayor John Smith (D) convicted. (1990)</li>", section="Texas")
        c = li_entries("<li>Mayor John Smith (D) convicted again. (1995)</li>", section="Ohio")
        self.assertEqual(len(cp.deduplicate(a + b + c)), 2)

    def test_unknown_entries_are_never_merged(self):
        entries = li_entries(
            '<li><a href="/wiki/Tax_collector">Tax collector</a>, York County Melissa Ann Arnold '
            'convicted of theft. (2015)</li>'
            '<li><a href="/wiki/Tax_collector">Tax collector</a>, Berks County, Jodie Mae Keller '
            'pleaded guilty. (2013)</li>')
        self.assertEqual(len(cp.deduplicate(entries)), 2)

    def test_list_link_is_not_a_person_identity(self):
        entries = li_entries(
            '<li><a href="/wiki/List_of_mayors_of_Springfield,_Missouri">Mayor of Springfield '
            'Thomas H Gideon</a> (R) convicted. (1920)</li>'
            '<li><a href="/wiki/List_of_mayors_of_Springfield,_Missouri">Mayor of Springfield '
            'John Doe</a> (R) convicted. (1925)</li>', section="Missouri")
        self.assertEqual([e.article for e in entries], ["", ""])
        self.assertEqual(len(cp.deduplicate(entries)), 2)

    def test_linked_person_merged_across_lists(self):
        a = li_entries('<li><a href="/wiki/Alan_Robbins">State Senator Alan Robbins</a> (D) resigned.</li>',
                       section="California")
        b = li_entries('<li>State Senator <a href="/wiki/Alan_Robbins">Alan Robbins</a> (D)</li>',
                       section="California")
        self.assertEqual(len(cp.deduplicate(a + b)), 1)


class TestCrawl(unittest.TestCase):
    def test_crawl_and_summary(self):
        src = fake_site()
        entries, pages, failed = cp.crawl(src, max_depth=2, verbose=False)
        self.assertEqual(pages, [
            cp.INDEX_TITLE,
            "List of Alabama politicians convicted of crimes",
            "List of Illinois politicians convicted of crimes",
            "List of Cook County politicians convicted of crimes",
        ])
        self.assertNotIn("List of American federal politicians convicted of crimes", src.requested)
        self.assertNotIn("List of Indiana politicians convicted of crimes", src.requested)

        self.assertEqual(failed, [])  # Ohio est introuvable (404), pas en échec réseau
        s = cp.summarize(entries, pages, failed)
        # Alabama : R=2 (Hubbard, White), D=4 (Siegelman, Langford, McNair, mot-clé), ?=2
        # Illinois (7 entrées) : D=4 (Blagojevich, Kerner, Burke, Jane), R=2 (Ryan, Bob),
        #                        + Hubbard, doublon de la liste Alabama
        # Cook : D=1 (DFL), Autre=1 (I)
        self.assertEqual(s["entrees_brutes"], 8 + 7 + 2)
        self.assertEqual(s["personnes_uniques"], 16)
        self.assertEqual(s["total"], {cp.DEM: 9, cp.REP: 4, cp.OTHER: 1, cp.UNKNOWN: 2})
        self.assertEqual(s["part_democrates_sur_D_plus_R"], round(100 * 9 / 13, 1))

    def test_network_failure_on_sublist_is_not_fatal(self):
        class Flaky(FakeSource):
            def get_html(self, title):
                if title == "List of Alabama politicians convicted of crimes":
                    raise cp.requests.ConnectionError("boom")
                return super().get_html(title)

        src = Flaky(fake_site().pages)
        entries, pages, failed = cp.crawl(src, verbose=False)
        self.assertEqual(failed, ["List of Alabama politicians convicted of crimes"])
        self.assertIn("List of Illinois politicians convicted of crimes", pages)
        self.assertEqual(cp.summarize(entries, pages, failed)["pages_en_echec"], failed)

    def test_network_failure_on_index_is_fatal(self):
        class Down(FakeSource):
            def get_html(self, title):
                raise cp.requests.ConnectionError("boom")

        with self.assertRaises(cp.requests.ConnectionError):
            cp.crawl(Down({}), verbose=False)

    def test_depth_limit(self):
        entries, pages, failed = cp.crawl(fake_site(), max_depth=1, verbose=False)
        self.assertNotIn("List of Cook County politicians convicted of crimes", pages)

    def test_redirect_not_read_twice(self):
        src = FakeSource(
            {cp.INDEX_TITLE: INDEX_HTML,
             "List of Alabama politicians convicted of crimes": ALABAMA_HTML},
            redirects={"List of Illinois politicians convicted of crimes":
                       "List of Alabama politicians convicted of crimes"},
        )
        entries, pages, failed = cp.crawl(src, max_depth=1, verbose=False)
        self.assertEqual(pages.count("List of Alabama politicians convicted of crimes"), 1)

    def test_strict_mode_drops_keyword_guesses(self):
        entries, pages, failed = cp.crawl(fake_site(), verbose=False)
        s = cp.summarize(cp.apply_strict(entries), pages)
        self.assertEqual(s["total"][cp.DEM], 8)
        self.assertEqual(s["total"][cp.UNKNOWN], 3)

    def test_csv_output(self):
        entries, pages, failed = cp.crawl(fake_site(), verbose=False)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "out.csv"
            cp.write_csv(entries, path)
            with path.open(encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), len(entries))
        dup = [r for r in rows if r["compte_dans_total"] != "oui"]
        self.assertEqual([r["nom"] for r in dup], ["Mike Hubbard"])


class TestWikiClient(unittest.TestCase):
    def test_request_and_cache(self):
        class Resp:
            status_code = 200
            headers = {}

            def raise_for_status(self):
                pass

            def json(self):
                return {"parse": {"title": "Resolved", "text": "<p>x</p>"}}

        class Session:
            def __init__(self):
                self.headers = {}
                self.calls = []

            def get(self, url, params, timeout):
                self.calls.append(params)
                return Resp()

        with tempfile.TemporaryDirectory() as d:
            sess = Session()
            client = cp.WikiClient(delay=0, cache_dir=Path(d), session=sess)
            self.assertEqual(client.get_html("Foo"), ("Resolved", "<p>x</p>"))
            self.assertEqual(client.get_html("Foo"), ("Resolved", "<p>x</p>"))
            self.assertEqual(len(sess.calls), 1)  # 2e appel servi par le cache
            self.assertEqual(sess.calls[0]["action"], "parse")
            self.assertEqual(sess.calls[0]["redirects"], "1")
            self.assertIn("PartyConvictionCounter", sess.headers["User-Agent"])

    def test_missing_page(self):
        class Resp:
            status_code = 200
            headers = {}

            def raise_for_status(self):
                pass

            def json(self):
                return {"error": {"code": "missingtitle"}}

        class Session:
            headers = {}

            def get(self, url, params, timeout):
                return Resp()

        client = cp.WikiClient(delay=0, session=Session())
        with self.assertRaises(cp.PageNotFound):
            client.get_html("Nope")


if __name__ == "__main__":
    unittest.main()
