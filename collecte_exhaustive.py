#!/usr/bin/env python3
"""
Construit la base la plus exhaustive possible des élus d'États et locaux
américains condamnés, à partir de Wikipédia, ainsi que la composition
partisane des parlements des 50 États (le « nombre d'élus » par parti).

Sources, toutes sur Wikipédia :
  1. les 17 listes par décennie « List of 19x0s American state and local
     politicians convicted of crimes » (via compter_partis) ;
  2. les listes « List of United States state / local / unincorporated
     territory officials convicted of federal corruption offenses » ;
  3. l'arbre de catégories « American politicians convicted of crimes »
     (recherche deepcat), limité aux personnes ayant exercé un mandat d'État
     ou local et aucun mandat fédéral ;
  4. les pages « Political party strength in <État> » : sièges démocrates et
     républicains de chaque parlement d'État, année par année.

Le parti vient du marqueur de la liste (« (D) », « (R) »...) quand la
personne y figure ; sinon de son article (catégories « Democratic Party
members of... », champ « party » de l'infobox).

Sorties (dossier resultats/ par défaut) :
  base_exhaustive.csv          une ligne par personne condamnée
  sieges_parlements_etats.csv  sièges D / R / autres par État et par année
  collecte.json                bilan : apport de chaque source, contrôles

Usage :
    python collecte_exhaustive.py                 # ~150 requêtes, 20-40 min
    python collecte_exhaustive.py --cache-dir cache/   (relance instantanée)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, Tag

import compter_partis as cp
from compter_partis import DEM, OTHER, REP, UNKNOWN

STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut",
    "Delaware", "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa",
    "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan",
    "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire",
    "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio",
    "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington", "West Virginia",
    "Wisconsin", "Wyoming",
]
DC = "Washington, D.C."
TERRITORIES = ["Puerto Rico", "Guam", "U.S. Virgin Islands", "Northern Mariana Islands",
               "American Samoa"]
ALIASES = {
    "District of Columbia": DC, "Northern Marianas Islands": "Northern Mariana Islands",
    "Virgin Islands": "U.S. Virgin Islands",
}
_PLACES = sorted([DC, *STATES, *TERRITORIES, *ALIASES], key=len, reverse=True)
_PLACE_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in _PLACES) + r")(?![\w])")

DECADE_LISTS_INDEX = cp.INDEX_TITLE
FEDERAL_LISTS = {
    "List of United States state officials convicted of federal corruption offenses": "état",
    "List of United States local officials convicted of federal corruption offenses": "local",
    "List of United States unincorporated territory officials convicted of federal "
    "corruption offenses": "territoire",
}
CATEGORY_SEARCH = 'deepcat:"American politicians convicted of crimes" -deepcat:"Donald Trump"'

SRC_DECADES = "listes_decennies"
SRC_FEDERAL = "listes_corruption_federale"
SRC_CATEGORIES = "categories"

# --------------------------------------------------------------------------
# Lieux
# --------------------------------------------------------------------------


def find_places(text: str) -> list[str]:
    """États / territoires cités dans un texte, sous leur nom canonique."""
    return [ALIASES.get(m.group(1), m.group(1)) for m in _PLACE_RE.finditer(text or "")]


def place_of(text: str) -> str:
    places = find_places(text)
    return Counter(places).most_common(1)[0][0] if places else ""


# --------------------------------------------------------------------------
# Lecture d'un article : parti, État, mandats, année de condamnation
# --------------------------------------------------------------------------

CATEGORY_RE = re.compile(r"\[\[\s*Category\s*:\s*([^\]|]+)", re.IGNORECASE)
FEDERAL_RE = re.compile(
    r"members of the united states house of representatives|united states senators|"
    r"members of the united states senate|vice presidents of the united states|"
    r"presidents of the united states|united states secretaries of|"
    r"united states federal judges|judges of the united states|united states attorneys|"
    r"delegates to the united states house|members of the united states congress|"
    r"united states cabinet|united states ambassadors|"
    # Nommage actuel : « Democratic Party United States representatives from Ohio »
    r"united states representatives|"
    r"(?:treasurers|attorneys general|secretaries|solicitors general|postmasters general) "
    r"of the united states|united states (?:deputy |assistant |under )?secretaries|"
    r"united states attorneys general|united states district court judges|"
    r"united states court of appeals judges",
    re.IGNORECASE,
)
_ASSEMBLIES = (r"house of representatives|senate|assembly|house of delegates|legislature|"
               r"general assembly|general court")
LEGISLATOR_CAT_RE = re.compile(
    rf"members of the (?!united states)[^,]*\b(?:{_ASSEMBLIES})\b|"
    r"state (?:senators|legislators|representatives)\b",
    re.IGNORECASE,
)
STATE_LOCAL_RE = re.compile(
    rf"members of the (?!united states)[^,]*\b(?:{_ASSEMBLIES}|council|board of supervisors|"
    r"board of aldermen|board of education|commission)\b|"
    r"state (?:senators|legislators|representatives|governors|treasurers|auditors|comptrollers|"
    r"attorneys general|cabinet secretaries|court judges|supreme court justices|"
    r"insurance commissioners)\b|"
    r"^(?:governors|lieutenant governors|secretaries of state|attorneys general|treasurers|"
    r"state treasurers|state auditors|auditors|comptrollers|state controllers) of |"
    r"mayors (?:of|in)\b|council members|councillors|councilmembers|aldermen|alderman|"
    r"selectmen|county commissioners|county executives|county judges|county officials|"
    r"county clerks|county treasurers|sheriffs|school board members|borough presidents|"
    r"district attorneys|state court judges|public service commissioners",
    re.IGNORECASE,
)
PARTY_CAT_RE = re.compile(
    r"^(?:Democratic|Republican|Democratic[–-]Farmer[–-]Labor) Party\b|\b(?:Democrats|Republicans)$"
)
CONVICTION_SENTENCE_RE = re.compile(
    r"\b(?:convicted|convicting|conviction|pleaded guilty|pled guilty|plead guilty|"
    r"found guilty|guilty plea|plea of guilty|pleaded no contest|nolo contendere|sentenced)\b",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"\b(18[3-9]\d|19\d\d|20[0-2]\d)\b")
LEGISLATOR_TEXT_RE = re.compile(
    r"\b(?:State (?:Senators?|Representatives?|Rep\.?|Sen\.?|Assembly(?:man|woman|member)|"
    r"Delegates?|Legislators?)|Assembly(?:man|woman|member)|Assembly member|House of Delegates|"
    r"Delegate|state legislator|state senator|state representative|Speaker of the|"
    r"Senate President|President of the [\w ]*Senate|Majority Leader|Minority Leader|"
    r"Member of the [\w ]*(?:House|Senate|Assembly|Legislature))\b",
    re.IGNORECASE,
)


def balanced_template(wikitext: str, start: int) -> str:
    """Contenu d'un modèle {{...}} qui commence à `start`, accolades imbriquées comprises."""
    depth, i = 0, start
    while i < len(wikitext) - 1:
        pair = wikitext[i:i + 2]
        if pair == "{{":
            depth += 1
            i += 2
            continue
        if pair == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return wikitext[start:i]
            continue
        i += 1
    return wikitext[start:]


def infobox(wikitext: str) -> str:
    m = re.search(r"\{\{\s*Infobox", wikitext, re.IGNORECASE)
    return balanced_template(wikitext, m.start()) if m else ""


def party_signals(text: str) -> set[str]:
    """Partis mentionnés dans un champ d'infobox ou un nom de catégorie."""
    t = re.sub(r"Democratic[-–\s]Republican", " ", text, flags=re.IGNORECASE)
    t = re.sub(r"\b(?:Popular|Social|Christian) Democratic", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"\b(?:National|Liberal|Radical) Republican", " ", t, flags=re.IGNORECASE)
    out = set()
    if re.search(r"\bDemocrat(?:ic|s)?\b|\bDFL\b", t, re.IGNORECASE):
        out.add(DEM)
    if re.search(r"\bRepublicans?\b|\bGOP\b", t, re.IGNORECASE):
        out.add(REP)
    # Autre parti seulement si ni D ni R n'est mentionné.
    removed_lookalike = t != text  # « Democratic-Republican », « Popular Democratic »...
    if not out and (removed_lookalike or re.search(
            r"\b(?:Independent|Libertarian|Green|Whig|Socialist|Progressive|Populist|People's|"
            r"Reform|Know Nothing|American Party|Covenant|New Progressive|Working Families|"
            r"Conservative Party|Liberal Party|Prohibition|Greenback|Constitution Party|"
            r"Nonpartisan|Farmer[-–]Labor)\b", text, re.IGNORECASE)):
        out.add(OTHER)
    return out


def decide_party(signals: set[str]) -> str:
    if DEM in signals and REP not in signals:
        return DEM
    if REP in signals and DEM not in signals:
        return REP
    if DEM in signals and REP in signals:
        return "Les deux (changement de parti)"
    if OTHER in signals:
        return OTHER
    return UNKNOWN


def plain_text(wikitext: str) -> str:
    t = re.sub(r"<!--.*?-->", " ", wikitext, flags=re.S)
    t = re.sub(r"<ref[^>]*/>", " ", t)
    t = re.sub(r"<ref[^>]*>.*?</ref>", " ", t, flags=re.S)
    for _ in range(6):  # modèles, du plus imbriqué au plus externe
        t, n = re.subn(r"\{\{[^{}]*\}\}", " ", t)
        if not n:
            break
    t = re.sub(r"\[\[(?:Category|File|Image):[^\]]*\]\]", " ", t, flags=re.I)
    t = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", t)
    t = re.sub(r"'{2,}", "", t)
    return re.sub(r"\s+", " ", t)


def conviction_year(wikitext: str) -> int | None:
    """Année de condamnation estimée d'après le texte de l'article.

    Dans chaque phrase qui parle de condamnation, on prend l'année la plus
    proche du verbe ; on retient ensuite la décennie la plus fréquente (et sa
    première année citée). Contrôlé sur les personnes aussi présentes dans
    les listes par décennie : 86 % de décennies exactes, 97 % à une décennie
    près."""
    picks = []
    for sentence in re.split(r"(?<=[.!?])\s+", plain_text(wikitext)):
        verb = CONVICTION_SENTENCE_RE.search(sentence)
        if not verb:
            continue
        years = [(abs(m.start() - verb.start()), int(m.group(1)))
                 for m in YEAR_RE.finditer(sentence)]
        if years:
            picks.append(min(years)[1])
    if not picks:
        return None
    decade = Counter(y // 10 * 10 for y in picks).most_common(1)[0][0]
    return next(y for y in picks if y // 10 * 10 == decade)


@dataclass
class ArticleInfo:
    title: str
    party: str
    party_from_categories: str
    party_from_infobox: str
    state: str
    federal: bool
    state_local: bool
    legislator: bool
    year: int | None


def article_info(title: str, wikitext: str) -> ArticleInfo:
    cats = [c.strip() for c in CATEGORY_RE.findall(wikitext)]
    box = infobox(wikitext)
    box_party = set()
    # Valeur du champ « party » jusqu'au paramètre suivant (« | nom = »). Les liens
    # « [[Republican Party (United States)|Republican]] » ne coupent pas la valeur.
    for m in re.finditer(r"\|\s*party\d*\s*=(.*?)(?=\|\s*[\w ]+?\s*=|\Z)", box, re.S | re.I):
        box_party |= party_signals(plain_text(m.group(1)))
    cat_party = set()
    for c in cats:
        if PARTY_CAT_RE.search(c):
            cat_party |= party_signals(c)
    state = ""
    for c in cats:
        m = re.match(r"(.+?) politicians convicted of crimes$", c)
        if m and len(set(find_places(m.group(1)))) == 1:
            state = find_places(m.group(1))[0]
            break
    if not state:
        state = place_of(" | ".join(cats))
    return ArticleInfo(
        title=title,
        party=decide_party(cat_party | box_party),
        party_from_categories=decide_party(cat_party),
        party_from_infobox=decide_party(box_party),
        state=state,
        federal=any(FEDERAL_RE.search(c) for c in cats),
        state_local=any(STATE_LOCAL_RE.search(c) for c in cats),
        legislator=any(LEGISLATOR_CAT_RE.search(c) for c in cats),
        year=conviction_year(wikitext),
    )


def fetch_articles(client: cp.WikiClient, titles: list[str],
                   verbose: bool = True) -> tuple[dict[str, str], dict[str, str]]:
    """Wikitexte des articles, par paquets de 50.

    Retourne (titre canonique -> wikitexte, titre demandé -> titre canonique)."""
    texts: dict[str, str] = {}
    canon: dict[str, str] = {}
    unique = list(dict.fromkeys(t for t in titles if t))
    for i in range(0, len(unique), 50):
        batch = unique[i:i + 50]
        if verbose:
            print(f"  articles {i + 1}-{i + len(batch)} / {len(unique)}", file=sys.stderr)
        mapping = {t: t for t in batch}
        cont: dict = {}
        while True:
            d = client.api(action="query", prop="revisions", rvprop="content", rvslots="main",
                           titles="|".join(batch), redirects=1, **cont)
            q = d.get("query", {})
            for step in ("normalized", "redirects"):
                for x in q.get(step, []):
                    for k, v in mapping.items():
                        if v == x["from"]:
                            mapping[k] = x["to"]
            for p in q.get("pages", []):
                revs = p.get("revisions")
                if revs:
                    texts[p["title"]] = revs[0]["slots"]["main"]["content"]
            if "continue" not in d:
                break
            cont = {k: v for k, v in d["continue"].items()}
        canon.update(mapping)
    return texts, canon


# --------------------------------------------------------------------------
# Listes « convicted of federal corruption offenses » (tableaux sans parti)
# --------------------------------------------------------------------------

@dataclass
class TableRow:
    name: str
    article: str
    office: str
    role: str
    level: str
    page: str


def parse_federal_list(html: str, page: str, level: str) -> list[TableRow]:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(".mw-parser-output") or soup
    for sel in cp.NOISE_SELECTORS:
        for node in root.select(sel):
            node.decompose()
    cp.remove_skipped_sections(root)
    out = []
    for table in root.find_all("table", class_="wikitable"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [cp.clean_text(c.get_text(" ")) for c in rows[0].find_all(["th", "td"])]
        office_col = next((i for i, h in enumerate(headers) if h.lower() == "office"), 1)
        role = headers[0] if headers else ""
        for tr in rows[1:]:
            cells = tr.find_all(["td", "th"], recursive=False)
            if len(cells) <= office_col:
                continue
            name = cp.clean_text(cells[0].get_text(" "))
            if not name:
                continue
            links = [cp.link_title(a) for a in cells[0].find_all("a", href=True)]
            links = [t for t in links if t]
            out.append(TableRow(name, links[0] if links else "",
                                cp.clean_text(cells[office_col].get_text(" ")), role, level, page))
    return out


# --------------------------------------------------------------------------
# Composition des parlements d'États (« Political party strength in X »)
# --------------------------------------------------------------------------

def expand_table(table: Tag) -> list[list[Tag | None]]:
    """Grille du tableau, cellules fusionnées (rowspan / colspan) recopiées."""
    grid: dict[tuple[int, int], Tag] = {}
    rows = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]
    ncols = 0
    for r, tr in enumerate(rows):
        c = 0
        for cell in tr.find_all(["th", "td"], recursive=False):
            while (r, c) in grid:
                c += 1
            rs = int(re.sub(r"\D", "", str(cell.get("rowspan", "1"))) or 1)
            cs = int(re.sub(r"\D", "", str(cell.get("colspan", "1"))) or 1)
            for dr in range(rs):
                for dc in range(cs):
                    grid[(r + dr, c + dc)] = cell
            c += cs
            ncols = max(ncols, c)
    return [[grid.get((r, c)) for c in range(ncols)] for r in range(len(rows))]


def is_legislature_label(label: str) -> bool:
    low = label.lower()
    return (any(k in low for k in ("senate", "house", "assembly", "delegates", "legislature",
                                   "general court"))
            and not any(k in low for k in ("u.s.", "united states", "congress", "senator",
                                           "class", "speaker")))


# DFL : démocrates du Minnesota ; IR : « Independent-Republicans », nom des
# républicains du Minnesota de 1975 à 1995. Les sièges vacants ne comptent pas.
DEM_CODES = {"D", "DFL"}
REP_CODES = {"R", "IR"}


def parse_composition(text: str) -> tuple[int, int, int] | None:
    """« 88R, 62D, 2PO, 1Proh » -> (D, R, autres)."""
    pairs = re.findall(r"(\d+)\s*([A-Za-z][A-Za-z.]*)", text)
    if not pairs:
        return None
    d = sum(int(n) for n, code in pairs if code in DEM_CODES)
    r = sum(int(n) for n, code in pairs if code in REP_CODES)
    o = sum(int(n) for n, code in pairs if code not in DEM_CODES | REP_CODES | {"vac."})
    return d, r, o


def parse_party_strength(html: str) -> dict[int, tuple[int, int, int]]:
    """Sièges (D, R, autres) des deux chambres réunies, par année.

    Certaines pages découpent l'historique en plusieurs tableaux (Alabama :
    1817-1882 puis 1883-aujourd'hui) : les années de tous les tableaux sont
    réunies, le premier tableau l'emportant si une année apparaît deux fois."""
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(".mw-parser-output") or soup
    for node in root.select("sup.reference, .reference, style, script"):
        node.decompose()
    merged: dict[int, tuple[int, int, int]] = {}
    for table in root.find_all("table", class_="wikitable"):
        grid = expand_table(table)
        if not grid:
            continue
        n_head = 0
        while n_head < len(grid) and all(c is None or c.name == "th" for c in grid[n_head]):
            n_head += 1
        if not n_head:
            continue
        labels = []
        for c in range(len(grid[0])):
            parts = []
            for r in range(n_head):
                cell = grid[r][c]
                t = cp.clean_text(cell.get_text(" ")) if cell is not None else ""
                if t and t not in parts:
                    parts.append(t)
            labels.append(" ".join(parts))
        cols = [c for c, lab in enumerate(labels) if is_legislature_label(lab)]
        if not cols:
            continue
        years: dict[int, tuple[int, int, int]] = {}
        for row in grid[n_head:]:
            if row[0] is None:
                continue
            m = re.match(r"\s*(\d{4})", row[0].get_text(" "))
            if not m or int(m.group(1)) in years:
                continue
            total, seen, ok = [0, 0, 0], set(), True
            for c in cols:
                cell = row[c] if c < len(row) else None
                if cell is None:
                    ok = False
                    break
                if id(cell) in seen:
                    continue
                seen.add(id(cell))
                comp = parse_composition(cp.clean_text(cell.get_text(" ")))
                if comp is None:
                    ok = False
                    break
                total = [a + b for a, b in zip(total, comp)]
            if ok and total[0] + total[1] > 0:
                years[int(m.group(1))] = tuple(total)
        for y, v in years.items():
            merged.setdefault(y, v)
    return merged


def fetch_seats(client: cp.WikiClient, verbose: bool = True) -> tuple[list[dict], list[str]]:
    rows, missing = [], []
    for state in STATES:
        candidates = [f"Political party strength in {state}"]
        if state == "Georgia":
            candidates.insert(0, "Political party strength in Georgia (U.S. state)")
        if state in ("New York", "Washington"):
            candidates.insert(0, f"Political party strength in {state} (state)")
        years = {}
        for title in candidates:
            try:
                _, html = client.get_html(title)
            except cp.PageNotFound:
                continue
            years = parse_party_strength(html)
            if years:
                break
        if verbose:
            span = f"{min(years)}-{max(years)}" if years else "aucune donnée"
            print(f"  sièges {state} : {len(years)} années ({span})", file=sys.stderr)
        if not years:
            missing.append(state)
        for y, (d, r, o) in sorted(years.items()):
            rows.append({"etat": state, "annee": y, "democrates": d, "republicains": r,
                         "autres": o})
    return rows, missing


# --------------------------------------------------------------------------
# Fusion
# --------------------------------------------------------------------------

@dataclass
class Person:
    name: str
    article: str = ""
    party: str = UNKNOWN
    party_source: str = ""
    state: str = ""
    decade: int | None = None
    year: int | None = None
    level: str = ""
    legislator: bool = False
    office: str = ""
    sources: list[str] = field(default_factory=list)
    article_party: str = ""

    def add_source(self, s: str) -> None:
        if s not in self.sources:
            self.sources.append(s)


def decade_of_page(page: str) -> int | None:
    m = re.search(r"(\d{4})s", page)
    return int(m.group(1)) if m else None


def build(client: cp.WikiClient, verbose: bool = True) -> tuple[list[Person], dict]:
    report: dict = {}

    # 1. Listes par décennie
    entries, pages, failed = cp.crawl(client, DECADE_LISTS_INDEX, verbose=verbose)
    entries = cp.deduplicate(entries)
    report["listes_decennies"] = {"pages": len(pages), "pages_en_echec": failed,
                                  "personnes": len(entries)}

    # 2. Listes de condamnations fédérales pour corruption
    table_rows: list[TableRow] = []
    for title, level in FEDERAL_LISTS.items():
        resolved, html = client.get_html(title)
        table_rows += parse_federal_list(html, resolved, level)
    report["listes_corruption_federale"] = {"lignes": len(table_rows)}

    # 3. Catégories
    cat_titles, offset = [], 0
    while True:
        d = client.api(action="query", list="search", srsearch=CATEGORY_SEARCH, srnamespace=0,
                       srlimit=500, sroffset=offset, srprop="")
        cat_titles += [x["title"] for x in d["query"]["search"]]
        if "continue" not in d:
            break
        offset = d["continue"]["sroffset"]
    report["categories"] = {"articles": len(cat_titles)}

    # Articles de toutes les personnes ayant un lien
    wanted = [e.article for e in entries if e.article] + \
             [r.article for r in table_rows if r.article] + cat_titles
    texts, canon = fetch_articles(client, wanted, verbose)
    infos = {t: article_info(t, wt) for t, wt in texts.items()}

    people: dict[str, Person] = {}

    def key_for(article: str, fallback: str) -> str:
        if article:
            return "wiki:" + canon.get(article, article)
        return fallback

    for e in entries:
        art = canon.get(e.article, e.article) if e.article else ""
        k = key_for(e.article, "liste:" + cp.person_key(e))
        p = people.get(k)
        if p is None:
            text_office = e.text[:cp.find_marker(e.text)[1]] if cp.find_marker(e.text) else e.text
            p = people[k] = Person(
                name=e.name, article=art, party=e.party,
                party_source="marqueur de la liste" if e.party != UNKNOWN else "",
                state=place_of(e.section), decade=decade_of_page(e.page),
                level="local" if e.subsection.lower() == "local" else "état",
                legislator=bool(LEGISLATOR_TEXT_RE.search(text_office)), office=e.text[:200])
        p.add_source(SRC_DECADES)

    for r in table_rows:
        art = canon.get(r.article, r.article) if r.article else ""
        k = key_for(r.article, f"table:{r.name.casefold()}|{r.office.casefold()}")
        p = people.get(k)
        if p is None:
            p = people[k] = Person(
                name=r.name, article=art, state=place_of(r.office), level=r.level,
                legislator=bool(LEGISLATOR_TEXT_RE.search(r.office)
                                or re.search(r"legislat", r.role, re.I)),
                office=f"{r.role} : {r.office}")
        p.add_source(SRC_FEDERAL)

    excluded = Counter()
    for t in cat_titles:
        art = canon.get(t, t)
        k = "wiki:" + art
        info = infos.get(art)
        if k in people:
            people[k].add_source(SRC_CATEGORIES)
            continue
        if info is None:
            excluded["article introuvable"] += 1
            continue
        if info.federal:
            excluded["mandat fédéral"] += 1
            continue
        if not info.state_local:
            excluded["aucun mandat d'État ou local identifié"] += 1
            continue
        people[k] = Person(name=art, article=art, level="état/local",
                           legislator=info.legislator, office="(catégories)")
        people[k].add_source(SRC_CATEGORIES)
    report["categories"]["exclus"] = dict(excluded)

    # Compléter avec les articles
    agree = Counter()
    year_check = Counter()
    for p in people.values():
        info = infos.get(p.article) if p.article else None
        if info is None:
            continue
        p.article_party = info.party
        if p.party == UNKNOWN and info.party != UNKNOWN:
            p.party = info.party
            p.party_source = "article (catégories / infobox)"
        elif p.party in (DEM, REP) and info.party in (DEM, REP):
            agree["identique" if p.party == info.party else "différent"] += 1
        if not p.state:
            p.state = info.state
        if p.decade is not None and info.year:
            year_check["même décennie" if info.year // 10 * 10 == p.decade else
                       "décennie différente"] += 1
        if p.decade is None and info.year:
            p.year = info.year
            p.decade = info.year // 10 * 10
        # Pour les listes par décennie, la fonction au moment des faits est dans le texte ;
        # sinon, on se fie aux catégories de l'article.
        if SRC_DECADES not in p.sources:
            p.legislator = p.legislator or info.legislator

    report["controle_parti_liste_vs_article"] = dict(agree)
    report["controle_decennie_liste_vs_article"] = dict(year_check)
    persons = sorted(people.values(), key=lambda p: (p.decade or 0, p.state, p.name))
    report["total_personnes"] = len(persons)
    report["apport_par_source"] = {
        "listes_decennies": sum(SRC_DECADES in p.sources for p in persons),
        "en_plus_via_listes_corruption_federale": sum(
            p.sources[0] == SRC_FEDERAL for p in persons),
        "en_plus_via_categories": sum(p.sources[0] == SRC_CATEGORIES for p in persons),
    }
    return persons, report


SRC_WIKIDATA = "wikidata"


def enrich_with_wikidata(persons: list[Person], sparql, verbose: bool = True) -> dict:
    """Complète le parti par Wikidata (P102) et ajoute les condamnés (P1399) absents."""
    import sources_complementaires as sc

    report: dict = {}
    by_article = {p.article: p for p in persons if p.article}
    parties = sc.wikidata_parties(sparql, list(by_article), verbose=verbose)
    filled, agree = 0, Counter()
    for title, labels in parties.items():
        p = by_article.get(title)
        if p is None or not labels:
            continue
        wd = decide_party(set().union(*(party_signals(l) for l in labels)))
        if p.party == UNKNOWN and wd != UNKNOWN:
            p.party, p.party_source = wd, "Wikidata (P102)"
            filled += 1
        elif p.party in (DEM, REP) and wd in (DEM, REP):
            agree["identique" if p.party == wd else "différent"] += 1
    report["partis_completes"] = filled
    report["controle_parti_base_vs_wikidata"] = dict(agree)

    added, skipped = 0, Counter()
    for wp in sc.wikidata_convicted(sparql):
        known = by_article.get(wp["title"]) if wp["title"] else None
        if known is not None:
            known.add_source(SRC_WIKIDATA)
            continue
        positions = " | ".join(wp["positions"])
        if sc.FEDERAL_POSITION_RE.search(positions):
            skipped["mandat fédéral"] += 1
            continue
        if not sc.STATE_LOCAL_POSITION_RE.search(positions):
            skipped["aucun mandat d'État ou local"] += 1
            continue
        year = min(wp["years"]) if wp["years"] else None
        person = Person(
            name=wp["label"] or wp["item"], article=wp["title"],
            party=decide_party(set().union(set(), *(party_signals(l) for l in wp["parties"]))),
            party_source="Wikidata (P102)", state=place_of(positions),
            year=year, decade=year // 10 * 10 if year else None, level="état/local",
            legislator=bool(sc.LEGISLATOR_POSITION_RE.search(positions)),
            office=positions[:200], sources=[SRC_WIKIDATA])
        if person.party == UNKNOWN:
            person.party_source = ""
        persons.append(person)
        if person.article:
            by_article[person.article] = person
        added += 1
    report["personnes_ajoutees"] = added
    report["exclues"] = dict(skipped)
    return report


def write_people(persons: list[Person], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["nom", "article", "parti", "source_parti", "etat", "decennie",
                    "annee_condamnation", "niveau", "parlementaire_etat", "sources",
                    "parti_selon_article", "fonction_ou_texte"])
        for p in persons:
            w.writerow([p.name, p.article, p.party, p.party_source, p.state,
                        p.decade or "", p.year or "", p.level,
                        "oui" if p.legislator else "non", ";".join(p.sources),
                        p.article_party, p.office])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=Path("resultats"), help="dossier de sortie")
    ap.add_argument("--cache-dir", type=Path, default=Path("cache"),
                    help="cache des réponses de Wikipédia (défaut : cache/)")
    ap.add_argument("--delay", type=float, default=1.0, help="pause entre requêtes (s)")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    client = cp.WikiClient(delay=args.delay, cache_dir=args.cache_dir, verbose=True)

    import sources_complementaires as sc

    print("1/4  Condamnés : listes, tableaux, catégories...", file=sys.stderr)
    persons, report = build(client)

    print("2/4  Wikidata : partis et condamnés absents de Wikipédia...", file=sys.stderr)
    report["wikidata"] = enrich_with_wikidata(persons, sc.Sparql(args.cache_dir))
    persons.sort(key=lambda p: (p.decade or 0, p.state, p.name))
    report["total_personnes"] = len(persons)
    report["apport_par_source"]["en_plus_via_wikidata"] = report["wikidata"]["personnes_ajoutees"]
    write_people(persons, args.out / "base_exhaustive.csv")

    print("3/4  Sièges des parlements d'États (Wikipédia, Klarner)...", file=sys.stderr)
    fields = ["etat", "annee", "democrates", "republicains", "autres"]
    seats, missing = fetch_seats(client)
    klarner = sc.klarner_seats(args.cache_dir)
    for name, rows in (("sieges_parlements_etats.csv", seats), ("sieges_klarner.csv", klarner)):
        with (args.out / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    report["sieges"] = {"lignes_etat_annee": len(seats), "etats_sans_donnees": missing,
                        "controle_wikipedia_vs_klarner": sc.compare_seats(seats, klarner)}

    print("4/4  Condamnations fédérales (ministère de la Justice)...", file=sys.stderr)
    doj = sc.doj_convictions(args.cache_dir)
    with (args.out / "doj_condamnations_etats_locaux.csv").open("w", newline="",
                                                                encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["annee", "condamnes_etats", "condamnes_locaux", "rapport_source"])
        for y, v in doj.items():
            w.writerow([y, v["etat"], v["local"], v["rapport"]])
    report["doj"] = {"annees": f"{min(doj)}-{max(doj)}",
                     "total_condamnes_etats_et_locaux": sum(v["etat"] + v["local"]
                                                            for v in doj.values())}
    (args.out / "collecte.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
