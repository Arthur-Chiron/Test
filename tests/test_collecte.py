"""Tests hors ligne de collecte_exhaustive.py.

Lancer :  python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import collecte_exhaustive as ce  # noqa: E402
import compter_partis as cp  # noqa: E402
from compter_partis import DEM, OTHER, REP, UNKNOWN  # noqa: E402


class TestPlaces(unittest.TestCase):
    def test_find_places(self):
        self.assertEqual(ce.find_places("Mayor of Newark, New Jersey"), ["New Jersey"])
        self.assertEqual(ce.find_places("West Virginia House of Delegates"), ["West Virginia"])
        self.assertEqual(ce.find_places("Arkansas Senate"), ["Arkansas"])
        self.assertEqual(ce.find_places("Washington, D.C., politicians"), [ce.DC])
        self.assertEqual(ce.find_places("District of Columbia"), [ce.DC])
        self.assertEqual(ce.find_places("Northern Marianas Islands"), ["Northern Mariana Islands"])
        self.assertEqual(ce.place_of("Kansas City, Missouri | Missouri state senators"), "Missouri")


class TestParty(unittest.TestCase):
    def test_signals(self):
        cases = {
            "[[Democratic Party (United States)|Democratic]]": {DEM},
            "Republican": {REP},
            "[[Democratic–Farmer–Labor Party|Democratic–Farmer–Labor]]": {DEM},
            "Democratic-Republican": {OTHER},
            "[[Popular Democratic Party (Puerto Rico)|Popular Democratic]]": {OTHER},
            "[[New Progressive Party (Puerto Rico)|New Progressive]]": {OTHER},
            "Independent": {OTHER},
            "Whig": {OTHER},
            "Democratic (before 1995)<br>Republican (1995–present)": {DEM, REP},
            "": set(),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(ce.party_signals(text), expected)

    def test_decide(self):
        self.assertEqual(ce.decide_party({DEM}), DEM)
        self.assertEqual(ce.decide_party({REP, OTHER}), REP)
        self.assertEqual(ce.decide_party({DEM, REP}), "Les deux (changement de parti)")
        self.assertEqual(ce.decide_party({OTHER}), OTHER)
        self.assertEqual(ce.decide_party(set()), UNKNOWN)


ARTICLE = """{{Short description|American politician}}
{{Infobox officeholder
| name = John Doe
| office = Member of the [[Ohio House of Representatives]]
| term_start = 1995
| party = [[Republican Party (United States)|Republican]]
| spouse = {{marriage|Jane|1980}}
}}
'''John Doe''' (born 1950) is an American politician who served in the Ohio House.

In March 2004, Doe was indicted. He was convicted of bribery in 2005 and sentenced in 2006.<ref>{{cite web|year=1999}}</ref>

== Elections ==
{{Election box candidate with party link|party = Democratic Party (United States)|candidate = Rival}}

[[Category:1950 births]]
[[Category:Republican Party members of the Ohio House of Representatives]]
[[Category:Ohio politicians convicted of crimes]]
"""


class TestArticleInfo(unittest.TestCase):
    def test_article(self):
        info = ce.article_info("John Doe", ARTICLE)
        # Le parti de l'adversaire (boîte d'élection) n'est pas pris en compte.
        self.assertEqual(info.party, REP)
        self.assertEqual(info.party_from_infobox, REP)
        self.assertEqual(info.party_from_categories, REP)
        self.assertEqual(info.state, "Ohio")
        self.assertFalse(info.federal)
        self.assertTrue(info.state_local)
        self.assertTrue(info.legislator)
        self.assertEqual(info.year, 2005)

    def test_federal_and_no_office(self):
        fed = ce.article_info("X", "[[Category:Members of the United States House of "
                                   "Representatives from Ohio]]\n[[Category:Ohio state senators]]")
        self.assertTrue(fed.federal)
        none = ce.article_info("Y", "Activist. He was convicted in 1970.\n"
                                    "[[Category:American political activists]]")
        self.assertFalse(none.state_local)
        self.assertEqual(none.year, 1970)

    def test_local_offices(self):
        for cat in ["Mayors of Detroit", "Chicago City Council members",
                    "Members of the Baltimore City Council", "Pennsylvania sheriffs",
                    "Governors of Illinois", "Members of the Massachusetts General Court",
                    "Members of the West Virginia House of Delegates"]:
            with self.subTest(cat=cat):
                self.assertTrue(ce.article_info("Z", f"[[Category:{cat}]]").state_local)


PARTY_STRENGTH_HTML = """
<div class="mw-parser-output"><table class="wikitable">
<tr><th rowspan="2">Year</th><th>Executive</th><th colspan="2">General Assembly</th>
    <th colspan="2">United States Congress</th></tr>
<tr><th>Governor</th><th>State Senate</th><th>State House</th><th>U.S. Senator</th><th>U.S. House</th></tr>
<tr><th>1901</th><td rowspan="2">Yates (R)</td><td rowspan="2">32R, 19D<sup class="reference">[1]</sup></td>
    <td>81R, 72D</td><td rowspan="3">Cullom (R)</td><td>11D, 11R</td></tr>
<tr><th>1902</th><td>88R, 62D, 2PO, 1Proh</td><td>12R, 10D</td></tr>
<tr><th>1903</th><td>Deneen (R)</td><td colspan="2">DR majority</td><td>13R, 9D</td></tr>
</table></div>
"""


class TestSeats(unittest.TestCase):
    def test_composition(self):
        self.assertEqual(ce.parse_composition("88R, 62D, 2PO, 1Proh"), (62, 88, 3))
        self.assertEqual(ce.parse_composition("40DFL, 27R"), (40, 27, 0))
        self.assertIsNone(ce.parse_composition("DR majority"))

    def test_party_strength_table(self):
        years = ce.parse_party_strength(PARTY_STRENGTH_HTML)
        # 1901 : Sénat 32R 19D + Chambre 81R 72D ; la délégation au Congrès est ignorée.
        self.assertEqual(years[1901], (91, 113, 0))
        # 1902 : le Sénat (rowspan) est recopié.
        self.assertEqual(years[1902], (81, 120, 3))
        # 1903 : pas d'effectifs chiffrés -> année ignorée.
        self.assertNotIn(1903, years)

    def test_history_split_over_two_tables(self):
        second = PARTY_STRENGTH_HTML.replace("1901", "1951").replace("1902", "1952") \
                                    .replace("1903", "1953")
        html = PARTY_STRENGTH_HTML.replace("</div>", "") + second.replace(
            '<div class="mw-parser-output">', "")
        years = ce.parse_party_strength(html)
        self.assertEqual(sorted(years), [1901, 1902, 1951, 1952])


FEDERAL_HTML = """
<div class="mw-parser-output"><table class="wikitable">
<tr><th>Mayor</th><th>Office</th><th>Crime(s)</th><th>Notes</th></tr>
<tr><td><a href="/wiki/Peter_Cammarano">Peter Cammarano</a></td><td>Mayor of Hoboken, New Jersey</td>
    <td>Hobbs Act</td><td>[9]</td></tr>
<tr><td>Jane Unlinked</td><td>Mayor of Gary, Indiana</td><td>Fraud</td><td></td></tr>
</table></div>
"""


class TestFederalList(unittest.TestCase):
    def test_rows(self):
        rows = ce.parse_federal_list(FEDERAL_HTML, "P", "local")
        self.assertEqual([(r.name, r.article, r.office, r.role) for r in rows], [
            ("Peter Cammarano", "Peter Cammarano", "Mayor of Hoboken, New Jersey", "Mayor"),
            ("Jane Unlinked", "", "Mayor of Gary, Indiana", "Mayor"),
        ])


class FakeClient:
    """Faux Wikipédia : listes, tableaux, recherche deepcat et articles."""

    INDEX = ('<div class="mw-parser-output"><ul><li><a href="/wiki/'
             'List_of_2000s_American_state_and_local_politicians_convicted_of_crimes">2000s</a>'
             '</li></ul></div>')
    DECADE = ('<div class="mw-parser-output"><h2>New Jersey</h2><ul>'
              '<li>Mayor of Hoboken <a href="/wiki/Peter_Cammarano_III">Peter Cammarano</a> (D) '
              'was convicted. (2009)</li>'
              '<li>State Senator Unlinked Person (R) was convicted. (2005)</li>'
              '</ul></div>')

    def __init__(self):
        self.pages = {
            cp.INDEX_TITLE: self.INDEX,
            "List of 2000s American state and local politicians convicted of crimes": self.DECADE,
        }
        for title in ce.FEDERAL_LISTS:
            self.pages[title] = FEDERAL_HTML if "local" in title else "<div></div>"
        self.articles = {
            "Peter Cammarano": "[[Category:Mayors of Hoboken, New Jersey]]\n"
                               "[[Category:New Jersey Democrats]]\nConvicted in 2009.",
            "Ohio Man": "{{Infobox officeholder|party=Republican}}\nHe pleaded guilty in 1998.\n"
                        "[[Category:Members of the Ohio House of Representatives]]",
            "Federal Guy": "[[Category:Members of the United States House of Representatives "
                           "from Ohio]]\n[[Category:Ohio state senators]]",
            "Activist": "[[Category:American activists]]",
        }

    def get_html(self, title):
        if title not in self.pages:
            raise cp.PageNotFound(title)
        return title, self.pages[title]

    def api(self, **params):
        if params.get("list") == "search":
            titles = ["Peter Cammarano", "Ohio Man", "Federal Guy", "Activist"]
            return {"query": {"search": [{"title": t} for t in titles]}}
        titles = params["titles"].split("|")
        redirects = [{"from": "Peter Cammarano III", "to": "Peter Cammarano"}]
        pages = [{"title": t, "revisions": [{"slots": {"main": {"content": self.articles[t]}}}]}
                 for t in {next((r["to"] for r in redirects if r["from"] == x), x) for x in titles}
                 if t in self.articles]
        return {"query": {"redirects": redirects, "pages": pages}}


class TestBuild(unittest.TestCase):
    def test_merge_sources(self):
        persons, report = ce.build(FakeClient(), verbose=False)
        by_name = {p.name: p for p in persons}
        # Cammarano : dans la liste (lien via redirection), le tableau et les catégories.
        cam = next(p for p in persons if p.article == "Peter Cammarano")
        self.assertEqual(cam.party, DEM)
        self.assertEqual(cam.party_source, "marqueur de la liste")
        self.assertEqual(sorted(cam.sources),
                         sorted([ce.SRC_DECADES, ce.SRC_FEDERAL, ce.SRC_CATEGORIES]))
        self.assertEqual((cam.state, cam.decade), ("New Jersey", 2000))
        # Sans lien, présent seulement dans la liste ; parlementaire d'après le texte.
        unl = by_name["State Senator Unlinked Person"]
        self.assertEqual((unl.party, unl.legislator), (REP, True))
        # Tableau sans lien ni parti.
        jane = by_name["Jane Unlinked"]
        self.assertEqual((jane.party, jane.state, jane.level), (UNKNOWN, "Indiana", "local"))
        # Catégories : ajouté avec parti et décennie tirés de l'article.
        ohio = by_name["Ohio Man"]
        self.assertEqual((ohio.party, ohio.state, ohio.decade, ohio.legislator),
                         (REP, "Ohio", 1990, True))
        # Élu fédéral et militant sans mandat : exclus.
        self.assertNotIn("Federal Guy", by_name)
        self.assertNotIn("Activist", by_name)
        self.assertEqual(report["categories"]["exclus"],
                         {"mandat fédéral": 1, "aucun mandat d'État ou local identifié": 1})
        self.assertEqual(report["apport_par_source"], {
            "listes_decennies": 2, "en_plus_via_listes_corruption_federale": 1,
            "en_plus_via_categories": 1})
        self.assertEqual(len(persons), 4)


if __name__ == "__main__":
    unittest.main()
