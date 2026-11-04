#!/usr/bin/env python3
"""
Graphiques et analyse : élus démocrates et républicains condamnés, comparés au
nombre d'élus de chaque parti.

Entrées (produites par collecte_exhaustive.py) :
  resultats/base_exhaustive.csv          une ligne par personne condamnée
  resultats/sieges_parlements_etats.csv  sièges D / R par État et par année

Méthode de comparaison :
  - « attendu » : si démocrates et républicains avaient le même taux de
    condamnation, la part de démocrates parmi les condamnés d'un État et d'une
    décennie serait leur part des sièges du parlement de cet État pendant cette
    décennie. On somme cette probabilité sur tous les condamnés ;
  - taux : parlementaires d'États condamnés, rapportés au nombre moyen de
    sièges détenus par chaque parti pendant la décennie.

Sorties : resultats/graphiques/*.png, resultats/analyse.json, resultats/analyse.md
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

DEM, REP = "Démocrate", "Républicain"
STATES = set(__import__("collecte_exhaustive").STATES)

# Couleurs : bleu = démocrates, rouge = républicains (paire validée par le
# validateur de palette : contraste et daltonisme OK) ; gris pour le contexte.
C = {
    "dem": "#2a78d6", "rep": "#e34948",
    "dem_light": "#9ec5f4", "rep_light": "#f1abaa",
    "surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
    "grid": "#e1e0d9", "axis": "#c3c2b7",
}
SOURCE_NOTE = ("Sources : Wikipédia (listes et catégories d'élus condamnés ; pages « Political "
               "party strength in … »), téléchargées le {date}.")


# --------------------------------------------------------------------------
# Données
# --------------------------------------------------------------------------

def load(base: Path, seats_path: Path):
    with base.open(encoding="utf-8-sig") as f:
        persons = list(csv.DictReader(f))
    with seats_path.open(encoding="utf-8") as f:
        seats = [{k: (int(v) if k != "etat" else v) for k, v in r.items()}
                 for r in csv.DictReader(f)]
    return persons, seats


def seat_tables(seats):
    """(État, décennie) -> sièges moyens (D, R) ; année -> total national (D, R)."""
    by_sd = defaultdict(list)
    national = defaultdict(lambda: [0, 0])
    for r in seats:
        by_sd[(r["etat"], r["annee"] // 10 * 10)].append((r["democrates"], r["republicains"]))
        national[r["annee"]][0] += r["democrates"]
        national[r["annee"]][1] += r["republicains"]
    state_decade = {k: (sum(d for d, _ in v) / len(v), sum(r for _, r in v) / len(v))
                    for k, v in by_sd.items()}
    return state_decade, dict(sorted(national.items()))


def analyse(persons, seats):
    state_decade, national = seat_tables(seats)
    dr = [p for p in persons if p["parti"] in (DEM, REP)]
    out: dict = {
        "personnes": len(persons),
        "partis": dict(Counter(p["parti"] for p in persons).most_common()),
        "sources": dict(Counter(p["sources"].split(";")[0] for p in persons)),
    }

    # Condamnés par décennie
    by_decade = defaultdict(Counter)
    for p in dr:
        if p["decennie"]:
            by_decade[int(p["decennie"])][p["parti"]] += 1
    out["condamnes_par_decennie"] = {d: {DEM: c[DEM], REP: c[REP]}
                                     for d, c in sorted(by_decade.items())}
    out["condamnes_sans_decennie"] = sum(1 for p in dr if not p["decennie"])

    # Observé vs attendu (même État, même décennie)
    def compare(subset):
        exp = defaultdict(lambda: {"obs_D": 0, "obs_R": 0, "exp_D": 0.0, "var": 0.0})
        per_state = defaultdict(lambda: {"obs_D": 0, "n": 0, "exp_D": 0.0})
        covered = 0
        for p in subset:
            if not p["decennie"] or p["etat"] not in STATES:
                continue
            sd = state_decade.get((p["etat"], int(p["decennie"])))
            if not sd or sd[0] + sd[1] == 0:
                continue
            covered += 1
            share = sd[0] / (sd[0] + sd[1])
            for key in (int(p["decennie"]), "total"):
                e = exp[key]
                e["obs_D" if p["parti"] == DEM else "obs_R"] += 1
                e["exp_D"] += share
                e["var"] += share * (1 - share)
            s = per_state[p["etat"]]
            s["n"] += 1
            s["obs_D"] += p["parti"] == DEM
            s["exp_D"] += share
        return exp, per_state, covered

    exp, per_state, covered = compare(dr)

    def summarize_exp(e):
        n = e["obs_D"] + e["obs_R"]
        z = (e["obs_D"] - e["exp_D"]) / math.sqrt(e["var"]) if e["var"] else None
        return {"n": n, "observe_D": e["obs_D"], "observe_R": e["obs_R"],
                "attendu_D": round(e["exp_D"], 1), "attendu_R": round(n - e["exp_D"], 1),
                "part_D_observee": round(100 * e["obs_D"] / n, 1) if n else None,
                "part_D_attendue": round(100 * e["exp_D"] / n, 1) if n else None,
                "ecart_en_ecarts_types": round(z, 2) if z is not None else None}

    out["comparables"] = covered
    out["observe_vs_attendu"] = summarize_exp(exp["total"])
    out["observe_vs_attendu_par_decennie"] = {
        k: summarize_exp(v) for k, v in sorted((k, v) for k, v in exp.items() if k != "total")}
    out["par_etat"] = {
        st: {"n": v["n"], "part_D_observee": round(100 * v["obs_D"] / v["n"], 1),
             "part_D_attendue": round(100 * v["exp_D"] / v["n"], 1)}
        for st, v in sorted(per_state.items(), key=lambda kv: -kv[1]["n"])}

    # Contrôles de robustesse : la même comparaison sur des sous-ensembles.
    subsets = {
        "parlementaires_etats": [p for p in dr if p["parlementaire_etat"] == "oui"],
        "autres_elus": [p for p in dr if p["parlementaire_etat"] != "oui"],
        "listes_decennies_seules": [p for p in dr if "listes_decennies" in p["sources"]],
        "ajouts_hors_listes": [p for p in dr if "listes_decennies" not in p["sources"]],
        "avant_1970": [p for p in dr if p["decennie"] and int(p["decennie"]) < 1970],
        "depuis_1970": [p for p in dr if p["decennie"] and int(p["decennie"]) >= 1970],
    }
    out["robustesse"] = {name: summarize_exp(compare(sub)[0]["total"])
                         for name, sub in subsets.items()}

    # Sièges nationaux (somme des États disposant de données)
    out["sieges_nationaux_par_annee"] = {y: {"D": d, "R": r} for y, (d, r) in national.items()}
    seats_decade = defaultdict(lambda: [0.0, 0.0])
    for (st, dec), (d, r) in state_decade.items():
        seats_decade[dec][0] += d
        seats_decade[dec][1] += r
    out["part_D_sieges_par_decennie"] = {
        dec: round(100 * d / (d + r), 1) for dec, (d, r) in sorted(seats_decade.items()) if d + r}

    # Taux : parlementaires d'États condamnés pour 1 000 sièges
    leg = defaultdict(Counter)
    for p in dr:
        if (p["parlementaire_etat"] == "oui" and p["decennie"] and p["etat"] in STATES
                and (p["etat"], int(p["decennie"])) in state_decade):
            leg[int(p["decennie"])][p["parti"]] += 1
    rates = {}
    tot = {"D": [0, 0.0], "R": [0, 0.0]}
    for dec in sorted(seats_decade):
        d_seats, r_seats = seats_decade[dec]
        cd, cr = leg[dec][DEM], leg[dec][REP]
        if not (cd or cr) or not d_seats or not r_seats:
            continue
        rates[dec] = {"condamnes_D": cd, "condamnes_R": cr,
                      "sieges_moyens_D": round(d_seats), "sieges_moyens_R": round(r_seats),
                      "taux_D_pour_1000": round(1000 * cd / d_seats, 2),
                      "taux_R_pour_1000": round(1000 * cr / r_seats, 2)}
        tot["D"][0] += cd
        tot["D"][1] += d_seats
        tot["R"][0] += cr
        tot["R"][1] += r_seats
    out["parlementaires_taux_par_decennie"] = rates
    out["parlementaires_taux_total"] = {
        "condamnes_D": tot["D"][0], "condamnes_R": tot["R"][0],
        "taux_D_pour_1000_sieges_decennie": round(1000 * tot["D"][0] / tot["D"][1], 2),
        "taux_R_pour_1000_sieges_decennie": round(1000 * tot["R"][0] / tot["R"][1], 2),
    }
    return out


# --------------------------------------------------------------------------
# Graphiques
# --------------------------------------------------------------------------

def new_figure(title: str, subtitle: str, note: str, size=(10, 5.6)):
    fig, ax = plt.subplots(figsize=size, dpi=200)
    fig.patch.set_facecolor(C["surface"])
    ax.set_facecolor(C["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(C["axis"])
    ax.spines["bottom"].set_linewidth(1)
    ax.yaxis.grid(True, color=C["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0, labelcolor=C["ink2"], labelsize=9)
    fig.text(0.06, 0.95, title, fontsize=14, fontweight="bold", color=C["ink"], va="top")
    fig.text(0.06, 0.895, subtitle, fontsize=10, color=C["ink2"], va="top")
    fig.text(0.06, 0.025, note, fontsize=7.5, color=C["muted"], va="bottom")
    fig.subplots_adjust(left=0.08, right=0.84, top=0.80, bottom=0.14)
    return fig, ax


def legend(ax, handles_labels, loc="upper left"):
    handles, labels = zip(*handles_labels)
    leg = ax.legend(handles, labels, loc=loc, frameon=False, fontsize=9, labelcolor=C["ink2"])
    return leg


def decade_label(d: int) -> str:
    return f"{d}s"


def fr(x: float) -> str:
    """Nombre décimal à la française : 5,43."""
    return f"{x}".replace(".", ",")


def fig_condamnes_par_decennie(a, path, note):
    data = a["condamnes_par_decennie"]
    decades = sorted(data)
    x = range(len(decades))
    w = 0.38
    tot = a["partis"]
    fig, ax = new_figure(
        "Élus d'États et locaux condamnés, par décennie",
        f"Personnes recensées sur Wikipédia — {tot.get(DEM, 0)} démocrates, "
        f"{tot.get(REP, 0)} républicains au total", note)
    bd = ax.bar([i - w / 2 for i in x], [data[d][DEM] for d in decades], w, color=C["dem"],
                edgecolor=C["surface"], linewidth=1.5)
    br = ax.bar([i + w / 2 for i in x], [data[d][REP] for d in decades], w, color=C["rep"],
                edgecolor=C["surface"], linewidth=1.5)
    ax.set_xticks(list(x), [decade_label(d) for d in decades], rotation=0, fontsize=8)
    ax.set_ylabel("Personnes condamnées", color=C["ink2"], fontsize=9)
    legend(ax, [(bd, "Démocrates"), (br, "Républicains")])
    fig.savefig(path, facecolor=C["surface"])
    plt.close(fig)


def fig_sieges(a, path, note):
    nat = a["sieges_nationaux_par_annee"]
    years = sorted(int(y) for y in nat)
    years = [y for y in years if y >= 1850]
    d = [nat[y]["D"] for y in years]
    r = [nat[y]["R"] for y in years]
    fig, ax = new_figure(
        "Nombre d'élus : sièges des parlements d'États par parti",
        "Total des sièges (deux chambres) détenus par chaque parti, États disposant de données",
        note)
    ax.plot(years, d, color=C["dem"], linewidth=2, solid_capstyle="round")
    ax.plot(years, r, color=C["rep"], linewidth=2, solid_capstyle="round")
    for series, color, label in ((d, C["dem"], "Démocrates"), (r, C["rep"], "Républicains")):
        ax.plot(years[-1], series[-1], "o", color=color, markersize=5,
                markeredgecolor=C["surface"], markeredgewidth=1.5)
        ax.annotate(f"{label}\n{series[-1]:,}".replace(",", " "), (years[-1], series[-1]),
                    xytext=(8, 0), textcoords="offset points", va="center", fontsize=9,
                    color=C["ink2"])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v):,}".replace(",", " ")))
    ax.set_xlim(years[0], years[-1])
    ax.set_ylim(0, None)
    fig.savefig(path, facecolor=C["surface"])
    plt.close(fig)


def fig_part_democrate(a, path, note):
    ova = a["observe_vs_attendu_par_decennie"]
    decades = [d for d in sorted(ova) if ova[d]["n"] >= 10]
    if not decades:
        return
    seats = a["part_D_sieges_par_decennie"]
    obs = [ova[d]["part_D_observee"] for d in decades]
    exp = [ova[d]["part_D_attendue"] for d in decades]
    nat = [seats.get(d) for d in decades]
    fig, ax = new_figure(
        "Part des démocrates : parmi les condamnés et parmi les élus",
        "Par décennie, pour les décennies comptant au moins 10 condamnés comparables", note)
    series = [
        (obs, C["dem"], "Démocrates parmi les condamnés"),
        (exp, C["ink2"], "Attendu si même taux (mêmes États, même décennie)"),
        (nat, C["muted"], "Démocrates parmi les sièges d'États (ensemble du pays)"),
    ]
    handles = []
    for values, color, label in series:
        h, = ax.plot(decades, values, color=color, linewidth=2, marker="o", markersize=4.5,
                     markeredgecolor=C["surface"], markeredgewidth=1.2, solid_capstyle="round")
        handles.append((h, label))
    # Les lignes se rejoignent à droite : une légende plutôt que des étiquettes empilées.
    legend(ax, handles, loc="lower right")
    ax.axhline(50, color=C["axis"], linewidth=1)
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v)} %"))
    ax.set_xticks(decades, [decade_label(d) for d in decades], fontsize=8)
    fig.savefig(path, facecolor=C["surface"])
    plt.close(fig)


def fig_observe_attendu(a, path, note):
    t = a["observe_vs_attendu"]
    fig, ax = new_figure(
        "Condamnés observés et attendus si les deux partis avaient le même taux",
        f"{t['n']} condamnés dont l'État et la décennie sont connus ; « attendu » = répartition "
        "selon les sièges détenus par chaque parti", note, size=(10, 5.6))
    groups = [("Démocrates", t["observe_D"], t["attendu_D"], C["dem"], C["dem_light"]),
              ("Républicains", t["observe_R"], t["attendu_R"], C["rep"], C["rep_light"])]
    w = 0.32
    for i, (label, obs, exp, col, light) in enumerate(groups):
        b1 = ax.bar(i - w / 2 - 0.01, obs, w, color=col)
        b2 = ax.bar(i + w / 2 + 0.01, exp, w, color=light)
        for bar, val, txt in ((b1, obs, "observés"), (b2, exp, "attendus")):
            ax.annotate(f"{val:.0f}\n{txt}", (bar[0].get_x() + bar[0].get_width() / 2, val),
                        xytext=(0, 4), textcoords="offset points", ha="center", va="bottom",
                        fontsize=9, color=C["ink2"])
    ax.set_xticks([0, 1], ["Démocrates", "Républicains"], fontsize=10)
    ax.set_xlim(-0.7, 1.7)
    ax.set_ylim(0, max(t["observe_D"], t["attendu_D"], t["observe_R"], t["attendu_R"]) * 1.25)
    ax.set_ylabel("Personnes condamnées", color=C["ink2"], fontsize=9)
    fig.savefig(path, facecolor=C["surface"])
    plt.close(fig)


def fig_taux(a, path, note):
    rates = a["parlementaires_taux_par_decennie"]
    decades = [d for d in sorted(rates) if rates[d]["condamnes_D"] + rates[d]["condamnes_R"] >= 5]
    x = range(len(decades))
    w = 0.38
    tt = a["parlementaires_taux_total"]
    fig, ax = new_figure(
        "Parlementaires d'États condamnés, pour 1 000 sièges détenus par leur parti",
        f"Condamnés ayant siégé dans un parlement d'État. Toutes décennies : "
        f"{fr(tt['taux_D_pour_1000_sieges_decennie'])} (D) contre "
        f"{fr(tt['taux_R_pour_1000_sieges_decennie'])} (R) pour 1 000 sièges", note)
    bd = ax.bar([i - w / 2 for i in x], [rates[d]["taux_D_pour_1000"] for d in decades], w,
                color=C["dem"], edgecolor=C["surface"], linewidth=1.5)
    br = ax.bar([i + w / 2 for i in x], [rates[d]["taux_R_pour_1000"] for d in decades], w,
                color=C["rep"], edgecolor=C["surface"], linewidth=1.5)
    ax.set_xticks(list(x), [decade_label(d) for d in decades], fontsize=8)
    ax.set_ylabel("Condamnés pour 1 000 sièges", color=C["ink2"], fontsize=9)
    legend(ax, [(bd, "Démocrates"), (br, "Républicains")])
    fig.savefig(path, facecolor=C["surface"])
    plt.close(fig)


def fig_etats(a, path, note, top=15):
    states = list(a["par_etat"].items())[:top]
    states.reverse()
    fig, ax = new_figure(
        f"Les {top} États comptant le plus de condamnés : part des démocrates",
        "Parmi les condamnés, et attendue d'après les sièges détenus par chaque parti dans "
        "l'État aux mêmes décennies", note, size=(10, 6.6))
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color=C["grid"], linewidth=0.8)
    for i, (st, v) in enumerate(states):
        ax.plot([v["part_D_attendue"], v["part_D_observee"]], [i, i], color=C["axis"],
                linewidth=2, solid_capstyle="round", zorder=1)
        ax.plot(v["part_D_attendue"], i, "o", color=C["ink2"], markersize=7,
                markeredgecolor=C["surface"], markeredgewidth=1.5, zorder=2)
        ax.plot(v["part_D_observee"], i, "o", color=C["dem"], markersize=7,
                markeredgecolor=C["surface"], markeredgewidth=1.5, zorder=3)
    ax.set_yticks(range(len(states)), [f"{st} ({v['n']})" for st, v in states], fontsize=8.5)
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v)} %"))
    ax.axvline(50, color=C["axis"], linewidth=1)
    h1, = ax.plot([], [], "o", color=C["dem"], markersize=7)
    h2, = ax.plot([], [], "o", color=C["ink2"], markersize=7)
    ax.legend([h1, h2], ["Condamnés", "Attendu (sièges)"], loc="lower right", frameon=False,
              fontsize=9, labelcolor=C["ink2"])
    fig.subplots_adjust(left=0.2)
    fig.savefig(path, facecolor=C["surface"])
    plt.close(fig)


ROBUSTNESS_LABELS = {
    "ensemble": "Tous les condamnés comparables",
    "parlementaires_etats": "Parlementaires d'États seulement",
    "autres_elus": "Autres élus (locaux, exécutifs…)",
    "listes_decennies_seules": "Listes par décennie seules",
    "ajouts_hors_listes": "Ajouts hors listes (catégories…)",
    "avant_1970": "Condamnés avant 1970",
    "depuis_1970": "Condamnés depuis 1970",
}


def fig_robustesse(a, path, note):
    rows = [("ensemble", a["observe_vs_attendu"])] + list(a["robustesse"].items())
    rows = [(k, v) for k, v in rows if v["n"]]
    rows.reverse()
    fig, ax = new_figure(
        "Part des démocrates parmi les condamnés : observée et attendue",
        "Même comparaison sur différents sous-ensembles ; « attendue » d'après les sièges "
        "détenus dans le même État à la même décennie", note, size=(10, 5.6))
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color=C["grid"], linewidth=0.8)
    for i, (k, v) in enumerate(rows):
        lo, hi = sorted((v["part_D_attendue"], v["part_D_observee"]))
        ax.plot([lo, hi], [i, i], color=C["axis"], linewidth=2, solid_capstyle="round", zorder=1)
        ax.plot(v["part_D_attendue"], i, "o", color=C["ink2"], markersize=7,
                markeredgecolor=C["surface"], markeredgewidth=1.5, zorder=2)
        ax.plot(v["part_D_observee"], i, "o", color=C["dem"], markersize=7,
                markeredgecolor=C["surface"], markeredgewidth=1.5, zorder=3)
        gap = v["part_D_observee"] - v["part_D_attendue"]
        ax.annotate(f"{'+' if gap >= 0 else '−'}{fr(round(abs(gap), 1))} pts",
                    (max(v["part_D_attendue"], v["part_D_observee"]), i), xytext=(10, 0),
                    textcoords="offset points", va="center", fontsize=8.5, color=C["ink2"])
    ax.set_yticks(range(len(rows)),
                  [f"{ROBUSTNESS_LABELS[k]} ({v['n']})" for k, v in rows], fontsize=8.5)
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v)} %"))
    ax.axvline(50, color=C["axis"], linewidth=1)
    h1, = ax.plot([], [], "o", color=C["dem"], markersize=7)
    h2, = ax.plot([], [], "o", color=C["ink2"], markersize=7)
    ax.legend([h1, h2], ["Observée", "Attendue (sièges)"], loc="lower left", frameon=False,
              fontsize=9, labelcolor=C["ink2"])
    fig.subplots_adjust(left=0.3)
    fig.savefig(path, facecolor=C["surface"])
    plt.close(fig)


def write_markdown(a, path):
    t = a["observe_vs_attendu"]
    lines = [
        "# Analyse : condamnés démocrates vs républicains", "",
        f"- Personnes dans la base : **{a['personnes']}**",
        f"- Répartition : " + ", ".join(f"{k} {v}" for k, v in a["partis"].items()),
        f"- Comparables (parti D/R, État et décennie connus, sièges disponibles) : "
        f"**{a['comparables']}**", "",
        "## Observé et attendu si les deux partis avaient le même taux", "",
        "| | Démocrates | Républicains |", "|---|---:|---:|",
        f"| Observés | {t['observe_D']} | {t['observe_R']} |",
        f"| Attendus | {t['attendu_D']} | {t['attendu_R']} |", "",
        f"Part des démocrates : {t['part_D_observee']} % observée, {t['part_D_attendue']} % "
        f"attendue (écart de {t['ecart_en_ecarts_types']} écarts-types).", "",
        "## Contrôles de robustesse (même comparaison sur des sous-ensembles)", "",
        "| Sous-ensemble | Condamnés | Part D observée | Part D attendue | Écart (écarts-types) |",
        "|---|---:|---:|---:|---:|",
        *[f"| {ROBUSTNESS_LABELS[k]} | {v['n']} | {v['part_D_observee']} % | "
          f"{v['part_D_attendue']} % | {v['ecart_en_ecarts_types']} |"
          for k, v in a["robustesse"].items()], "",
        "## Par décennie", "",
        "| Décennie | Condamnés D | Condamnés R | Part D observée | Part D attendue | "
        "Part D des sièges (pays) |", "|---|---:|---:|---:|---:|---:|",
    ]
    for d, v in a["observe_vs_attendu_par_decennie"].items():
        lines.append(f"| {d}s | {v['observe_D']} | {v['observe_R']} | {v['part_D_observee']} % | "
                     f"{v['part_D_attendue']} % | {a['part_D_sieges_par_decennie'].get(d, '')} % |")
    lines += ["", "## Parlementaires d'États : condamnés pour 1 000 sièges", "",
              "| Décennie | Condamnés D | Sièges D | Taux D | Condamnés R | Sièges R | Taux R |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for d, v in a["parlementaires_taux_par_decennie"].items():
        lines.append(f"| {d}s | {v['condamnes_D']} | {v['sieges_moyens_D']} | "
                     f"{v['taux_D_pour_1000']} | {v['condamnes_R']} | {v['sieges_moyens_R']} | "
                     f"{v['taux_R_pour_1000']} |")
    tt = a["parlementaires_taux_total"]
    lines += ["", f"Toutes décennies : {tt['taux_D_pour_1000_sieges_decennie']} (D) contre "
                  f"{tt['taux_R_pour_1000_sieges_decennie']} (R) pour 1 000 sièges par décennie.",
              "", "## Par État", "", "| État | Condamnés | Part D observée | Part D attendue |",
              "|---|---:|---:|---:|"]
    for st, v in a["par_etat"].items():
        lines.append(f"| {st} | {v['n']} | {v['part_D_observee']} % | {v['part_D_attendue']} % |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path("resultats"),
                    help="dossier contenant base_exhaustive.csv et sieges_parlements_etats.csv")
    ap.add_argument("--date", default="", help="date de téléchargement (pour la note de source)")
    args = ap.parse_args(argv)
    persons, seats = load(args.dir / "base_exhaustive.csv",
                          args.dir / "sieges_parlements_etats.csv")
    a = analyse(persons, seats)
    out = args.dir / "graphiques"
    out.mkdir(parents=True, exist_ok=True)
    note = SOURCE_NOTE.format(date=args.date or "jour de la collecte")
    fig_condamnes_par_decennie(a, out / "1_condamnes_par_decennie.png", note)
    fig_sieges(a, out / "2_sieges_par_parti.png", note)
    fig_part_democrate(a, out / "3_part_des_democrates.png", note)
    fig_observe_attendu(a, out / "4_observe_vs_attendu.png", note)
    fig_taux(a, out / "5_taux_parlementaires.png", note)
    fig_etats(a, out / "6_etats.png", note)
    fig_robustesse(a, out / "7_robustesse.png", note)
    (args.dir / "analyse.json").write_text(json.dumps(a, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    write_markdown(a, args.dir / "analyse.md")
    t = a["observe_vs_attendu"]
    print(json.dumps({k: a[k] for k in ("personnes", "partis", "comparables")},
                     ensure_ascii=False))
    print("Observé vs attendu :", json.dumps(t, ensure_ascii=False))
    print("Taux parlementaires :", json.dumps(a["parlementaires_taux_total"], ensure_ascii=False))
    for k, v in a["robustesse"].items():
        print(f"  {k:26} n={v['n']:4}  D observé {v['part_D_observee']} %  attendu "
              f"{v['part_D_attendue']} %  écart {v['ecart_en_ecarts_types']} σ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
