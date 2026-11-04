"""Tests du calcul de graphiques.py (observé vs attendu, taux par siège)."""
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import graphiques as g  # noqa: E402

D, R = g.DEM, g.REP


def person(parti, etat, decennie, parlementaire="non"):
    return {"parti": parti, "etat": etat, "decennie": str(decennie) if decennie else "",
            "parlementaire_etat": parlementaire, "sources": "listes_decennies"}


SEATS = [
    # Illinois années 2000 : 75 % de sièges démocrates ; Ohio : 25 %.
    *({"etat": "Illinois", "annee": y, "democrates": 75, "republicains": 25, "autres": 0}
      for y in range(2000, 2010)),
    *({"etat": "Ohio", "annee": y, "democrates": 25, "republicains": 75, "autres": 0}
      for y in range(2000, 2010)),
]


class TestAnalyse(unittest.TestCase):
    def test_expected_uses_state_and_decade(self):
        persons = ([person(D, "Illinois", 2000, "oui")] * 3 + [person(R, "Illinois", 2000)]
                   + [person(R, "Ohio", 2000, "oui")] * 2 + [person(D, "Ohio", 2000)] * 2
                   + [person(D, "Guam", 2000), person(D, "Ohio", None)])
        a = g.analyse(persons, SEATS)
        t = a["observe_vs_attendu"]
        # Guam (pas un État) et la personne sans décennie sont exclus de la comparaison.
        self.assertEqual(a["comparables"], 8)
        self.assertEqual((t["observe_D"], t["observe_R"]), (5, 3))
        # Attendu : 4 x 0,75 (Illinois) + 4 x 0,25 (Ohio) = 4 démocrates.
        self.assertEqual((t["attendu_D"], t["attendu_R"]), (4.0, 4.0))
        var = 4 * 0.75 * 0.25 + 4 * 0.25 * 0.75
        self.assertEqual(t["ecart_en_ecarts_types"], round((5 - 4) / math.sqrt(var), 2))
        self.assertEqual(a["par_etat"]["Illinois"],
                         {"n": 4, "part_D_observee": 75.0, "part_D_attendue": 75.0})
        # Sièges : 100 D et 100 R en moyenne sur la décennie (deux États).
        self.assertEqual(a["part_D_sieges_par_decennie"], {2000: 50.0})
        rates = a["parlementaires_taux_par_decennie"][2000]
        self.assertEqual((rates["condamnes_D"], rates["condamnes_R"]), (3, 2))
        self.assertEqual((rates["taux_D_pour_1000"], rates["taux_R_pour_1000"]), (30.0, 20.0))

    def test_figures_are_written(self):
        persons = ([person(D, "Illinois", 2000, "oui")] * 12 + [person(R, "Ohio", 2000, "oui")] * 8)
        a = g.analyse(persons, SEATS)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            for fn in (g.fig_condamnes_par_decennie, g.fig_sieges, g.fig_part_democrate,
                       g.fig_observe_attendu, g.fig_taux, g.fig_etats, g.fig_robustesse):
                path = out / f"{fn.__name__}.png"
                fn(a, path, "note")
                self.assertGreater(path.stat().st_size, 10_000)
            g.write_markdown(a, out / "a.md")
            self.assertIn("| Illinois | 12 |", (out / "a.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
