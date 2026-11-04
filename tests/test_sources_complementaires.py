"""Tests hors ligne de sources_complementaires.py et de l'enrichissement Wikidata."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import collecte_exhaustive as ce  # noqa: E402
import sources_complementaires as sc  # noqa: E402
from compter_partis import DEM, REP, UNKNOWN  # noqa: E402

# Mise en page des rapports récents (tableau sur deux décennies).
MODERN = """
                                           TABLE II
               PROGRESS OVER THE LAST TWO DECADES:
                             2004   2005   2006   2007   2008   2009   2010   2011   2012   2013
FEDERAL OFFICIALS
Charged                      424    445    463    426    518    425    422    412    381    337
Convicted                    381    390    407    405    458    426    397    392    369    315
STATE OFFICIALS
Charged                      111     96    101    128    144     93    168     93    100    133
Convicted                     81     94    116     85    123    102    108    143     78    119
LOCAL OFFICIALS
Convicted                    252    232    241    275    246    257    280    276    295    303
TOTALS
Convicted                    1020 1,027 1,030 1,014 1,129 1,061 1,036 1,107 1,060 1,037
                             2014   2015   2016   2017   2018   2019   2020   2021   2022   2023 Totals
STATE OFFICIALS
Convicted                    109    97     125    68     72     63     30     43     68     58    1,782
LOCAL OFFICIALS
Convicted                    252    200    213    208    175    199    110    138    149    121   4,422
"""

# Mise en page du rapport 1983 (années sur la ligne « Federal Officials », texte OCR).
OLD_1983 = """
               TABLE I
State Officials
  Convicted                          65
                                                             TABLE 11
Federal Officials             1974         1975     1976       1977      1978   1979   1980      1981   1982    1983
-   Convicted                  ,   51        43      101            94     91    115       131    159    147     424
State Officials
-   Convicted                      23       18        35            38     56     32        51     66     43      65
local Officials
-   Convicted                      87       94      100        164       127    156        168   211    232      226
"""


class TestDoj(unittest.TestCase):
    def test_modern_layout(self):
        t = sc.parse_doj_table(MODERN)
        self.assertEqual(sorted(t), list(range(2004, 2024)))
        self.assertEqual(t[2004], {"etat": 81, "local": 252})
        self.assertEqual(t[2023], {"etat": 58, "local": 121})  # la colonne « Totals » est ignorée

    def test_1983_layout(self):
        t = sc.parse_doj_table(OLD_1983)
        self.assertEqual(sorted(t), list(range(1974, 1984)))
        self.assertEqual(t[1974], {"etat": 23, "local": 87})
        self.assertEqual(t[1983], {"etat": 65, "local": 226})


class TestSeats(unittest.TestCase):
    def test_compare(self):
        wiki = [{"etat": "Ohio", "annee": 1990, "democrates": 60, "republicains": 40, "autres": 0},
                {"etat": "Ohio", "annee": 1991, "democrates": 50, "republicains": 50, "autres": 0}]
        kl = [{"etat": "Ohio", "annee": 1990, "democrates": 60, "republicains": 40, "autres": 0},
              {"etat": "Ohio", "annee": 1991, "democrates": 40, "republicains": 60, "autres": 0},
              {"etat": "Iowa", "annee": 1991, "democrates": 1, "republicains": 1, "autres": 0}]
        c = sc.compare_seats(wiki, kl)
        self.assertEqual((c["etat_annees_comparees"], c["identiques"]), (2, 1))
        self.assertEqual(c["ecart_part_D_inferieur_a_2_points_pct"], 50.0)


class FakeSparql:
    def query(self, q):
        if "VALUES ?title" in q:
            return [{"title": "Known Unknown", "partyLabel": "Republican Party"},
                    {"title": "Known Dem", "partyLabel": "Democratic Party"}]
        return [
            {"item": "http://www.wikidata.org/entity/Q1", "itemLabel": "New Mayor",
             "partyLabel": "Democratic Party", "posLabel": "Mayor of Newark, New Jersey",
             "date": "1998-05-01T00:00:00Z"},
            {"item": "http://www.wikidata.org/entity/Q2", "itemLabel": "Congressman",
             "posLabel": "United States representative"},
            {"item": "http://www.wikidata.org/entity/Q3", "itemLabel": "Activist"},
            {"item": "http://www.wikidata.org/entity/Q4", "itemLabel": "Known Dem",
             "title": "Known Dem", "posLabel": "member of the Ohio Senate"},
        ]


class TestWikidataEnrichment(unittest.TestCase):
    def test_enrich(self):
        persons = [ce.Person(name="Known Unknown", article="Known Unknown"),
                   ce.Person(name="Known Dem", article="Known Dem", party=DEM)]
        rep = ce.enrich_with_wikidata(persons, FakeSparql(), verbose=False)
        self.assertEqual(persons[0].party, REP)
        self.assertEqual(persons[0].party_source, "Wikidata (P102)")
        self.assertIn(ce.SRC_WIKIDATA, persons[1].sources)
        self.assertEqual(rep["controle_parti_base_vs_wikidata"], {"identique": 1})
        added = persons[2:]
        self.assertEqual([(p.name, p.party, p.state, p.decade) for p in added],
                         [("New Mayor", DEM, "New Jersey", 1990)])
        self.assertEqual(rep["exclues"], {"mandat fédéral": 1, "aucun mandat d'État ou local": 1})
        self.assertNotEqual(persons[0].party, UNKNOWN)


if __name__ == "__main__":
    unittest.main()
