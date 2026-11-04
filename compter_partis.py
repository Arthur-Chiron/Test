#!/usr/bin/env python3
"""
Compte les démocrates et les républicains figurant dans les listes Wikipédia
« Lists of American state and local politicians convicted of crimes ».

La page d'origine est une « liste de listes » : elle renvoie vers des
sous-listes (par État, par période...). Le script :

  1. télécharge la page d'index via l'API MediaWiki (action=parse) ;
  2. suit tous les liens vers des sous-listes « List(s) of ... convicted ... »
     (hors listes fédérales et hors sections « See also », « References »...) ;
  3. extrait chaque entrée (puces <li> et lignes de tableaux « wikitable ») ;
  4. détermine le parti de chaque personne à partir des marqueurs habituels
     de Wikipédia : « (D) », « (R-TX) », « (Democrat) », « (DFL) »... ;
  5. affiche le décompte démocrates / républicains et écrit le détail en CSV.

Usage :
    python compter_partis.py
    python compter_partis.py --csv resultats.csv --json resume.json
    python compter_partis.py --strict          # uniquement les marqueurs explicites
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Protocol
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup, Tag

API_URL = "https://en.wikipedia.org/w/api.php"
INDEX_TITLE = "Lists of American state and local politicians convicted of crimes"
# Wikimedia demande un User-Agent identifiable :
# https://meta.wikimedia.org/wiki/User-Agent_policy
USER_AGENT = (
    "PartyConvictionCounter/1.0 (https://github.com/Arthur-Chiron/Test) "
    f"python-requests/{requests.__version__}"
)

DEM = "Démocrate"
REP = "Républicain"
OTHER = "Autre"
UNKNOWN = "Indéterminé"
PARTIES = (DEM, REP, OTHER, UNKNOWN)

# Méthode de détection, de la plus fiable à la moins fiable.
METHOD_MARKER = "marqueur"     # « (D) », « (R-TX) », « (Democrat) »...
METHOD_COLUMN = "colonne"      # colonne « Party » d'un tableau
METHOD_HEADING = "titre"       # entrée rangée sous un titre « Democrats »
METHOD_KEYWORD = "mot-clé"     # « Democratic mayor of... » dans le texte
STRICT_METHODS = {METHOD_MARKER, METHOD_COLUMN, METHOD_HEADING}

# Sections qui ne contiennent pas d'entrées et dont on ne suit pas les liens.
SKIP_SECTIONS = {
    "see also", "references", "notes", "external links", "further reading",
    "sources", "bibliography", "footnotes", "citations", "notes and references",
}

# Blocs d'habillage à retirer avant l'analyse.
NOISE_SELECTORS = [
    ".navbox", ".vertical-navbox", ".sidebar", ".infobox", ".metadata",
    ".reflist", ".references", ".mw-references-wrap", "#toc", ".toc",
    ".hatnote", ".mw-editsection", ".portalbox", ".noprint", ".ambox",
    "sup.reference", ".mw-cite-backlink", "style", "script",
]

# Titre d'une sous-liste à suivre : « List of ... convicted ... ».
LIST_TITLE_RE = re.compile(r"^Lists? of .*\bconvicted\b", re.IGNORECASE)
EXCLUDED_TITLE_RE = re.compile(r"\bfederal\b", re.IGNORECASE)

# Marqueur de parti entre parenthèses, juste après le nom de la personne.
# Les lettres seules (D, R, I, L) doivent être suivies d'un séparateur pour
# ne pas confondre « (D.C.) » ou « (R.I.) » avec un parti. Les mots sont
# acceptés quelle que soit la casse (« (populist) » existe sur Wikipédia).
PAREN_MARKER_RE = re.compile(
    r"""
    \(\s*
    (?:
        (?P<letter>[DRIL])\s*(?=[-–—‑,/;:)\s])
      | (?P<word>(?i:
            Democratic[-–\s]Republican
          | Popular\ Democratic | New\ Progressive | PPD | PNP | PIP   # Porto Rico
          | Covenant | CP                                            # Mariannes du Nord
          | Green[-–\s]Rainbow | GRP
          | Democratic[-–\s]+Farmer[-–\s]+Labor
          | DFL | Democrat(?:ic)? | Dem
          | Republican | Rep | GOP
          | Independent | Ind | Libertarian | Green | Whig | Socialist
          | Progressive | Populist | Reform | Nonpartisan | Non-partisan
          | Know[-\s]Nothing | Federalist | Conservative | Liberal
          | Constitution | Prohibition | Greenback | Unionist | Readjuster
          | Working\ Families
        ))(?![A-Za-z])
    )
    """,
    re.VERBOSE,
)

# Repli : mention du parti n'importe où dans le texte de l'entrée.
KEYWORD_RE = re.compile(r"\b(Democratic[-–]Republican|Democratic|Democrats?|Republicans?|GOP)\b")


# --------------------------------------------------------------------------
# Détection du parti
# --------------------------------------------------------------------------

def classify_token(token: str) -> str:
    """Convertit un marqueur (« D », « Republican », « DFL »...) en parti."""
    t = token.strip()
    if re.match(r"Democratic[-–\s]Republican", t, re.IGNORECASE):
        return OTHER  # parti jeffersonien du XIXe siècle, ni D ni R
    low = t.lower()
    if t == "D" or low.startswith("dem") or low == "dfl":
        return DEM
    if t == "R" or low.startswith("rep") or low == "gop":
        return REP
    return OTHER


def find_markers(text: str) -> list[tuple[str, int, int]]:
    """Tous les marqueurs de parti entre parenthèses : [(parti, début, fin)].
    La fin est placée après la parenthèse fermante (« (R-TX) » en entier)."""
    out = []
    for m in PAREN_MARKER_RE.finditer(text):
        close = text.find(")", m.end())
        end = close + 1 if close != -1 else m.end()
        out.append((classify_token(m.group("letter") or m.group("word")), m.start(), end))
    return out


def find_marker(text: str) -> tuple[str, int] | None:
    """Premier marqueur de parti entre parenthèses : (parti, position)."""
    markers = find_markers(text)
    return (markers[0][0], markers[0][1]) if markers else None


def party_from_keyword(text: str) -> str | None:
    m = KEYWORD_RE.search(text)
    return classify_token(m.group(1)) if m else None


def party_from_heading(*headings: str) -> str | None:
    """« Democrats », « Republican officials »... -> parti (titre le plus précis d'abord)."""
    for h in headings:
        if not h:
            continue
        has_d = re.search(r"\bDemocrat", h, re.IGNORECASE)
        has_r = re.search(r"\bRepublican", h, re.IGNORECASE)
        if has_d and not has_r:
            return DEM
        if has_r and not has_d:
            return REP
    return None


def party_from_cell(text: str) -> str | None:
    """Contenu d'une cellule « Party » : « Democratic », « R », « Republican Party »..."""
    t = text.strip()
    if not t:
        return None
    m = re.match(
        r"(Democratic[-–\s]Republican|Democratic|Democrat|DFL|Dem|D|Republican|Rep|GOP|R)(?![A-Za-z])",
        t,
    )
    if m:
        return classify_token(m.group(1))
    return party_from_keyword(t) or OTHER


# --------------------------------------------------------------------------
# Analyse HTML d'une page
# --------------------------------------------------------------------------

@dataclass
class Entry:
    page: str
    section: str
    subsection: str
    name: str
    party: str
    method: str
    text: str
    article: str = ""  # article Wikipédia de la personne, si son nom est un lien


def clean_text(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.;:)\]])", r"\1", s)
    s = re.sub(r"([(\[])\s+", r"\1", s)
    return s


def heading_level(tag: Tag) -> int | None:
    """Niveau d'un titre, y compris le nouvel habillage <div class="mw-heading">."""
    if not isinstance(tag, Tag):
        return None
    if re.fullmatch(r"h[1-6]", tag.name or ""):
        return int(tag.name[1])
    if tag.name == "div" and "mw-heading" in (tag.get("class") or []):
        h = tag.find(re.compile(r"^h[1-6]$"))
        return int(h.name[1]) if h else None
    return None


def link_title(a: Tag) -> str | None:
    """« /wiki/List_of_X#Y » -> « List of X » (None pour les liens hors articles)."""
    href = a.get("href") or ""
    if not href.startswith("/wiki/"):
        return None
    title = unquote(href[len("/wiki/"):]).split("#", 1)[0].replace("_", " ").strip()
    if not title or ":" in title:  # File:, Category:, Help:...
        return None
    return title


def is_list_title(title: str | None) -> bool:
    return bool(
        title
        and LIST_TITLE_RE.search(title)
        and not EXCLUDED_TITLE_RE.search(title)
    )


def remove_skipped_sections(root: Tag) -> None:
    """Supprime « See also », « References »... et tout ce qu'ils contiennent."""
    for h in root.find_all(re.compile(r"^h[2-6]$")):
        if h.decomposed or clean_text(h.get_text(" ")).lower() not in SKIP_SECTIONS:
            continue
        level = int(h.name[1])
        parent = h.parent if isinstance(h.parent, Tag) else None
        start = parent if parent is not None and "mw-heading" in (parent.get("class") or []) else h
        to_remove = [start]
        for sib in start.next_siblings:
            lvl = heading_level(sib)
            if lvl is not None and lvl <= level:
                break
            to_remove.append(sib)
        for node in to_remove:
            if isinstance(node, Tag):
                node.decompose()
            else:
                node.extract()


def own_copy(li: Tag) -> Tag:
    """Copie d'un <li> sans ses sous-listes imbriquées."""
    c = copy.copy(li)
    for sub in c.find_all(["ul", "ol", "dl"]):
        sub.decompose()
    return c


# Fin du « sujet » d'une phrase : « X (D) and Y (R) were convicted of... ».
# Les marqueurs placés avant ce verbe désignent les personnes condamnées ;
# ceux qui suivent désignent en général d'autres personnes (victimes,
# complices cités, élus fédéraux...).
SUBJECT_END_RE = re.compile(
    r"\b(?:was|were|is|are|has|had|have|pleaded|pled|plead|pleads|convicted|"
    r"found|sentenced|guilty|served|resigned|received|admitted|indicted|charged|"
    r"jailed|imprisoned|acquitted|committed|died|who)\b",
    re.IGNORECASE,
)
# Sous-puce qui détaille la condamnation de la personne de la puce parente.
DETAIL_START_RE = re.compile(
    r"^(?:Found|Pleaded|Pled|Convicted|Sentenced|Was|Were|Served|Resigned|Received|"
    r"Admitted|Acquitted|Indicted|Charged|Jailed)\b"
)
# Virgule qui ne coupe pas un nom : « Otto Kerner, Jr. », « John Smith, III ».
NAME_SEPARATOR_RE = re.compile(r"[;:]|,(?!\s*(?:Jr|Sr|I{2,3}|IV)\b)")


def person_links(source: Tag) -> list[tuple[str, str]]:
    """(texte du lien, titre de l'article) pour chaque lien interne, les plus longs d'abord."""
    out = []
    for a in source.find_all("a", href=True):
        title = link_title(a)
        text = clean_text(a.get_text(" "))
        if title and text:
            out.append((text, title))
    return sorted(out, key=lambda x: -len(x[0]))


def name_before(text: str, start: int, end: int,
                links: list[tuple[str, str]]) -> tuple[str, str]:
    """Nom placé juste avant un marqueur : (nom, article).

    On préfère le lien qui précède immédiatement le marqueur
    (« State Representative [[Ed Henry]] (R) » -> « Ed Henry »).
    Sinon, on prend le texte depuis le dernier séparateur."""
    before = text[start:end].rstrip(" ,")
    for link_text, title in links:
        if before.endswith(link_text):
            # Un lien vers « List of mayors of X » n'identifie pas une personne.
            return link_text, ("" if re.match(r"Lists? of\b", title) else title)
    parts = NAME_SEPARATOR_RE.split(before)
    name = parts[-1] if parts else before
    name = re.sub(r"^\s*(?:(?:\d{4}s?|[-–—•*]|and|&)\s+)+", "", name).strip(" -–—*")
    return name[:80], ""


def entries_from_text(page: str, section: str, subsection: str, text: str,
                      name_source: Tag) -> list[Entry]:
    """Personne(s) décrite(s) par une puce ou une ligne de tableau."""
    links = person_links(name_source)
    markers = find_markers(text)
    if markers:
        first_end = markers[0][2]
        verb = SUBJECT_END_RE.search(text, first_end)
        subject_end = verb.start() if verb else len(text)
        out: list[Entry] = []
        seen: set[str] = set()
        prev_end = 0
        for party, m_start, m_end in markers:
            if out and m_start >= subject_end:
                break
            name, article = name_before(text, prev_end, m_start, links)
            prev_end = m_end
            key = (article or name).casefold()
            if key in seen:  # même personne citée deux fois dans la puce
                continue
            seen.add(key)
            out.append(Entry(page, section, subsection, name, party, METHOD_MARKER, text, article))
        return out

    heading_party = party_from_heading(subsection, section)
    keyword_party = party_from_keyword(text)
    if heading_party:
        party, method = heading_party, METHOD_HEADING
    elif keyword_party:
        party, method = keyword_party, METHOD_KEYWORD
    else:
        party, method = UNKNOWN, ""
    # Sans marqueur, le nom n'est qu'indicatif : le lien en tête de puce est souvent
    # une fonction (« [[Tax collector]], York County... »), donc pas d'identité
    # par article, et l'entrée ne sera jamais fusionnée avec une autre.
    name = clean_text(NAME_SEPARATOR_RE.split(re.split(r"\(", text, maxsplit=1)[0])[0])[:80]
    return [Entry(page, section, subsection, name, party, method, text)]


def parse_table(table: Tag, page: str, section: str, subsection: str) -> list[Entry]:
    rows = table.find_all("tr")
    if not rows:
        return []
    header_cells = rows[0].find_all(["th", "td"])
    headers = [clean_text(c.get_text(" ")).lower() for c in header_cells]
    party_col = next((i for i, h in enumerate(headers) if re.search(r"party|affiliation", h)), None)
    name_col = next((i for i, h in enumerate(headers)
                     if re.search(r"\b(name|politician|official|person|individual)\b", h)), 0)
    entries = []
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"], recursive=False)
        if not cells:
            continue
        text = clean_text(tr.get_text(" "))
        if not text:
            continue
        if party_col is not None and len(cells) == len(headers):
            party = party_from_cell(clean_text(cells[party_col].get_text(" ")))
            if party:
                cell = cells[name_col] if name_col < len(cells) else cells[0]
                name = clean_text(cell.get_text(" "))
                links = person_links(cell)
                article = links[0][1] if len(links) == 1 else ""
                entries.append(Entry(page, section, subsection, name, party, METHOD_COLUMN,
                                     text, article))
                continue
        entries.extend(entries_from_text(page, section, subsection, text, cells[0]))
    return entries


def parse_page(html: str, page: str) -> tuple[list[Entry], list[str]]:
    """Retourne (entrées trouvées, titres des sous-listes à suivre)."""
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(".mw-parser-output") or soup
    for sel in NOISE_SELECTORS:
        for node in root.select(sel):
            node.decompose()
    remove_skipped_sections(root)

    links: list[str] = []
    for a in root.find_all("a", href=True):
        t = link_title(a)
        if is_list_title(t) and t not in links:
            links.append(t)

    entries: list[Entry] = []
    section = subsection = ""
    for el in root.find_all(["h2", "h3", "h4", "h5", "li", "table"]):
        if el.name in ("h2", "h3", "h4", "h5"):
            title = clean_text(el.get_text(" "))
            if el.name == "h2":
                section, subsection = title, ""
            else:
                subsection = title
            continue
        if el.name == "table":
            if "wikitable" in (el.get("class") or []) and not el.find_parent("table"):
                entries.extend(parse_table(el, page, section, subsection))
            continue
        # <li>
        if el.find_parent("table"):
            continue
        own = own_copy(el)
        text = clean_text(own.get_text(" "))
        if not text:
            continue
        # Une puce qui ne fait que renvoyer vers une autre liste n'est pas une personne.
        titles = [link_title(a) for a in own.find_all("a", href=True)]
        titles = [t for t in titles if t]
        if re.match(r"Lists? of\b", text) or (titles and all(is_list_title(t) for t in titles)):
            continue
        has_children = el.find(["ul", "ol"]) is not None
        new = entries_from_text(page, section, subsection, text, own)
        # Puce « intitulé » (ex. « Chicago : ») dont les personnes sont en sous-liste.
        if has_children and new[0].method != METHOD_MARKER:
            continue
        # Sous-puce « Found guilty of... » sous « John McGee (R): » : c'est un détail
        # de la condamnation de la personne parente, déjà comptée.
        parent = el.find_parent("li")
        if (parent is not None and new[0].method != METHOD_MARKER
                and DETAIL_START_RE.match(text)
                and find_marker(clean_text(own_copy(parent).get_text(" ")))):
            continue
        entries.extend(new)
    return entries, links


# --------------------------------------------------------------------------
# Téléchargement
# --------------------------------------------------------------------------

class PageNotFound(Exception):
    pass


class HtmlSource(Protocol):
    def get_html(self, title: str) -> tuple[str, str]: ...


class WikiClient:
    """Client minimal de l'API MediaWiki, poli, avec reprises et cache disque.

    Wikipédia limite le débit (réponses 429 avec Retry-After) : le client
    attend le délai demandé puis réessaie."""

    def __init__(self, api_url: str = API_URL, delay: float = 0.5,
                 cache_dir: Path | None = None, max_retries: int = 8,
                 session: requests.Session | None = None, verbose: bool = False):
        self.api_url = api_url
        self.delay = delay
        self.cache_dir = cache_dir
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.verbose = verbose
        self._last = 0.0
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, title: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / (re.sub(r"[^\w.-]+", "_", title)[:150] + ".json")

    def _request(self, params: dict, what: str) -> dict:
        """Une requête à l'API, avec reprises. Lève PageNotFound si la page n'existe pas."""
        for attempt in range(self.max_retries):
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                r = self.session.get(self.api_url, params=params, timeout=60)
            except requests.RequestException as exc:
                if attempt == self.max_retries - 1:
                    raise
                print(f"  réseau : {exc} ; nouvel essai...", file=sys.stderr)
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                pause = float(r.headers.get("Retry-After") or 2 ** attempt)
                if self.verbose:
                    print(f"  [{r.status_code}] Wikipédia demande d'attendre {pause:.0f} s",
                          file=sys.stderr)
                time.sleep(pause)
                continue
            r.raise_for_status()
            data = r.json()
            err = data.get("error")
            if err:
                if err.get("code") == "maxlag":
                    time.sleep(float(r.headers.get("Retry-After") or 5))
                    continue
                if err.get("code") in ("missingtitle", "invalidtitle"):
                    raise PageNotFound(what)
                raise RuntimeError(f"API MediaWiki : {err}")
            return data
        raise RuntimeError(f"Échec du téléchargement de « {what} » après {self.max_retries} essais")

    def api(self, **params) -> dict:
        """Appel générique (action=query, list=search...), mis en cache sur disque."""
        params = {"format": "json", "formatversion": "2", "maxlag": "5",
                  **{k: str(v) for k, v in params.items()}}
        key = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / f"api_{key}.json" if self.cache_dir else None
        if path and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        data = self._request(params, params.get("titles") or params.get("srsearch")
                             or params.get("page") or "requête")
        if path:
            path.write_text(json.dumps(data), encoding="utf-8")
        return data

    def get_html(self, title: str) -> tuple[str, str]:
        path = self._cache_path(title)
        if path and path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data["title"], data["html"]
        params = {
            "action": "parse", "page": title, "prop": "text", "format": "json",
            "formatversion": "2", "redirects": "1", "disableeditsection": "1",
            "disabletoc": "1", "maxlag": "5",
        }
        data = self._request(params, title)
        result = data["parse"]["title"], data["parse"]["text"]
        if path:
            path.write_text(json.dumps({"title": result[0], "html": result[1]}), encoding="utf-8")
        return result


def normalize_title(t: str) -> str:
    t = t.replace("_", " ").strip()
    return (t[:1].upper() + t[1:]) if t else t


def crawl(source: HtmlSource, start: str = INDEX_TITLE, max_depth: int = 2,
          verbose: bool = True) -> tuple[list[Entry], list[str], list[str]]:
    """Parcourt la page d'index et ses sous-listes.

    Retourne (entrées, pages lues, pages en échec). Une sous-liste qu'on ne
    peut pas télécharger est signalée sans interrompre le parcours ; seul un
    échec sur la page de départ est fatal."""
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    seen: set[str] = set()
    pages: list[str] = []
    failed: list[str] = []
    entries: list[Entry] = []
    while queue:
        title, depth = queue.popleft()
        if normalize_title(title) in seen:
            continue
        seen.add(normalize_title(title))
        try:
            resolved, html = source.get_html(title)
        except PageNotFound:
            print(f"  ! page introuvable : {title}", file=sys.stderr)
            continue
        except (requests.RequestException, RuntimeError) as exc:
            if depth == 0:
                raise
            print(f"  ! échec du téléchargement de « {title} » : {exc}", file=sys.stderr)
            failed.append(title)
            continue
        if resolved != title and normalize_title(resolved) in seen:
            continue  # redirection vers une page déjà lue
        seen.add(normalize_title(resolved))
        page_entries, links = parse_page(html, resolved)
        pages.append(resolved)
        entries.extend(page_entries)
        if verbose:
            c = Counter(e.party for e in page_entries)
            print(f"  [{len(pages):>2}] {resolved} : {len(page_entries)} entrées "
                  f"(D={c[DEM]}, R={c[REP]})", file=sys.stderr)
        if depth < max_depth:
            for link in links:
                if normalize_title(link) not in seen:
                    queue.append((link, depth + 1))
    return entries, pages, failed


# --------------------------------------------------------------------------
# Comptage et sorties
# --------------------------------------------------------------------------

def person_key(e: Entry) -> str:
    """Identité d'une personne, prudente pour ne jamais fusionner deux personnes.

    - nom en lien : l'article Wikipédia (fiable d'une liste à l'autre) ;
    - nom sans lien mais parti explicite : nom + État (section) ;
    - sinon : le texte complet de l'entrée."""
    if e.article:
        return "wiki:" + e.article.casefold()
    if e.method in STRICT_METHODS and e.name:
        return "txt:" + e.section.casefold() + "|" + re.sub(r"\s+", " ", e.name).strip().casefold()
    return "entry:" + e.text.casefold()


def deduplicate(entries: Iterable[Entry]) -> list[Entry]:
    """Une personne citée dans plusieurs listes n'est comptée qu'une fois.
    On garde l'occurrence dont le parti a été trouvé de la façon la plus fiable."""
    rank = {METHOD_MARKER: 0, METHOD_COLUMN: 1, METHOD_HEADING: 2, METHOD_KEYWORD: 3, "": 4}
    best: dict[str, Entry] = {}
    order: list[str] = []
    for e in entries:
        k = person_key(e)
        if k not in best:
            order.append(k)
            best[k] = e
        elif rank[e.method] < rank[best[k].method]:
            best[k] = e
    return [best[k] for k in order]


def apply_strict(entries: Iterable[Entry]) -> list[Entry]:
    out = []
    for e in entries:
        if e.method not in STRICT_METHODS and e.party != UNKNOWN:
            e = Entry(**{**asdict(e), "party": UNKNOWN, "method": ""})
        out.append(e)
    return out


def summarize(entries: list[Entry], pages: list[str], failed: Iterable[str] = ()) -> dict:
    unique = deduplicate(entries)
    by_page: dict[str, Counter] = defaultdict(Counter)
    for e in unique:
        by_page[e.page][e.party] += 1
    totals = Counter(e.party for e in unique)
    d, r = totals[DEM], totals[REP]
    return {
        "pages_lues": pages,
        "pages_en_echec": list(failed),
        "entrees_brutes": len(entries),
        "personnes_uniques": len(unique),
        "total": {p: totals[p] for p in PARTIES},
        "total_brut": {p: Counter(e.party for e in entries)[p] for p in PARTIES},
        "part_democrates_sur_D_plus_R": round(100 * d / (d + r), 1) if d + r else None,
        "par_page": {pg: {p: c[p] for p in PARTIES} for pg, c in by_page.items()},
        "methodes": dict(Counter(e.method or "aucune" for e in unique)),
    }


def write_csv(entries: list[Entry], path: Path) -> None:
    unique_ids = {id(e) for e in deduplicate(entries)}
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["page", "section", "sous_section", "nom", "article", "parti", "methode",
                    "compte_dans_total", "texte"])
        for e in entries:
            w.writerow([e.page, e.section, e.subsection, e.name, e.article, e.party, e.method,
                        "oui" if id(e) in unique_ids else "non (doublon)", e.text])


def print_report(s: dict) -> None:
    t = s["total"]
    print()
    print("=" * 64)
    print("Politiciens d'États et locaux américains condamnés (Wikipédia)")
    print("=" * 64)
    print(f"Pages analysées        : {len(s['pages_lues'])}")
    if s["pages_en_echec"]:
        print(f"ATTENTION : {len(s['pages_en_echec'])} page(s) non téléchargée(s), "
              "décompte incomplet :")
        for title in s["pages_en_echec"]:
            print(f"  - {title}")
    print(f"Entrées trouvées       : {s['entrees_brutes']}")
    print(f"Personnes uniques      : {s['personnes_uniques']}")
    print("-" * 64)
    print(f"Démocrates             : {t[DEM]}")
    print(f"Républicains           : {t[REP]}")
    print(f"Autres partis          : {t[OTHER]}")
    print(f"Parti non déterminé    : {t[UNKNOWN]}")
    if s["part_democrates_sur_D_plus_R"] is not None:
        pd = s["part_democrates_sur_D_plus_R"]
        print(f"Répartition D / R      : {pd} % / {round(100 - pd, 1)} %")
    print("-" * 64)
    print("Détail par page (personnes uniques) :")
    width = max((len(p) for p in s["par_page"]), default=10)
    width = min(width, 70)
    print(f"  {'page':<{width}}  {'D':>5} {'R':>5} {'Autre':>6} {'?':>5}")
    for page, c in s["par_page"].items():
        print(f"  {page[:width]:<{width}}  {c[DEM]:>5} {c[REP]:>5} {c[OTHER]:>6} {c[UNKNOWN]:>5}")
    print("-" * 64)
    print("Méthodes de détection :", ", ".join(f"{k}={v}" for k, v in s["methodes"].items()))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default=INDEX_TITLE, help="titre de la page de départ")
    ap.add_argument("--max-depth", type=int, default=2,
                    help="profondeur de suivi des sous-listes (défaut : 2)")
    ap.add_argument("--csv", type=Path, default=Path("politiciens_condamnes.csv"),
                    help="fichier CSV du détail (défaut : politiciens_condamnes.csv)")
    ap.add_argument("--json", type=Path, help="fichier JSON du résumé (optionnel)")
    ap.add_argument("--strict", action="store_true",
                    help="ne compter que les partis indiqués explicitement "
                         "(marqueur, colonne Party ou titre de section)")
    ap.add_argument("--delay", type=float, default=0.5,
                    help="pause minimale entre deux requêtes, en secondes")
    ap.add_argument("--cache-dir", type=Path,
                    help="dossier où garder les pages téléchargées (relance hors ligne)")
    args = ap.parse_args(argv)

    print(f"Lecture de « {args.start} » et de ses sous-listes...", file=sys.stderr)
    client = WikiClient(delay=args.delay, cache_dir=args.cache_dir)
    try:
        entries, pages, failed = crawl(client, args.start, args.max_depth)
    except (requests.RequestException, RuntimeError) as exc:
        print(f"Impossible de lire « {args.start} » : {exc}", file=sys.stderr)
        return 1
    if args.strict:
        entries = apply_strict(entries)

    summary = summarize(entries, pages, failed)
    print_report(summary)
    write_csv(entries, args.csv)
    print(f"\nDétail écrit dans {args.csv}")
    if args.json:
        args.json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Résumé écrit dans {args.json}")
    # Code 2 : résultats écrits mais incomplets (au moins une sous-liste en échec).
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
