"""
Sources complémentaires à Wikipédia :

  - Wikidata (query.wikidata.org) : parti (P102) des personnes ayant un article,
    et personnes américaines condamnées (P1399) ayant exercé un mandat ;
  - Carl Klarner, « State Partisan Balance Data, 1937-2011 » (Harvard
    Dataverse, doi:10.7910/DVN/LZHMG3) : sièges D / R des parlements d'États ;
  - rapports annuels de la Public Integrity Section du ministère de la Justice
    (justice.gov) : nombre d'élus et d'agents d'États et locaux condamnés par
    la justice fédérale, chaque année depuis 1974.

Tous les téléchargements sont mis en cache dans le dossier de cache.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

import compter_partis as cp

SPARQL_URL = "https://query.wikidata.org/sparql"
KLARNER_DOI = "doi:10.7910/DVN/LZHMG3"
KLARNER_FILE = "Partisan_Balance_For_Use2011_06_09b.xlsx"
DATAVERSE = "https://dataverse.harvard.edu"
# Rapports retenus : chacun contient un tableau des 10 ou 20 dernières années.
DOJ_REPORTS = {
    2023: "https://www.justice.gov/media/1384436/dl?inline",   # 2004-2023
    2003: "https://www.justice.gov/media/1106871/dl?inline",   # 1984-2003
    1983: "https://www.justice.gov/media/1106971/dl?inline",   # 1974-1983
}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = cp.USER_AGENT
    return s


def _get(session, url, *, params=None, data=None, headers=None, timeout=120, tries=6):
    for attempt in range(tries):
        try:
            if data is not None:
                r = session.post(url, data=data, headers=headers, timeout=timeout)
            else:
                r = session.get(url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(float(r.headers.get("Retry-After") or 2 ** attempt))
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"Échec du téléchargement de {url}")


# --------------------------------------------------------------------------
# Wikidata
# --------------------------------------------------------------------------

class Sparql:
    def __init__(self, cache_dir: Path | None, delay: float = 1.0):
        self.cache_dir = cache_dir
        self.delay = delay
        self.session = _session()
        self._last = 0.0

    def query(self, q: str) -> list[dict]:
        key = hashlib.sha1(q.encode()).hexdigest()
        path = self.cache_dir / f"sparql_{key}.json" if self.cache_dir else None
        if path and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        r = _get(self.session, SPARQL_URL, data={"query": q},
                 headers={"Accept": "application/sparql-results+json"})
        rows = [{k: v["value"] for k, v in b.items()} for b in r.json()["results"]["bindings"]]
        if path:
            path.write_text(json.dumps(rows), encoding="utf-8")
        return rows


def _literal(title: str) -> str:
    return '"' + title.replace("\\", "\\\\").replace('"', '\\"') + '"@en'


def wikidata_parties(sparql: Sparql, titles: list[str], batch: int = 150,
                     verbose: bool = True) -> dict[str, list[str]]:
    """Titre d'article -> libellés anglais des partis (P102) de la personne."""
    out: dict[str, list[str]] = {}
    titles = sorted(set(t for t in titles if t))
    for i in range(0, len(titles), batch):
        chunk = titles[i:i + batch]
        if verbose:
            print(f"  Wikidata partis {i + 1}-{i + len(chunk)} / {len(titles)}", file=sys.stderr)
        q = ("SELECT ?title ?partyLabel WHERE { VALUES ?title { " + " ".join(map(_literal, chunk))
             + " } ?a schema:name ?title ; schema:isPartOf <https://en.wikipedia.org/> ; "
               "schema:about ?item . OPTIONAL { ?item wdt:P102 ?party . ?party rdfs:label "
               "?partyLabel . FILTER(LANG(?partyLabel) = \"en\") } }")
        for row in sparql.query(q):
            labels = out.setdefault(row["title"], [])
            if row.get("partyLabel") and row["partyLabel"] not in labels:
                labels.append(row["partyLabel"])
    return out


FEDERAL_POSITION_RE = re.compile(
    r"United States (?:representative|senator|Secretary|Attorney|ambassador|Deputy|Assistant)|"
    r"member of the United States (?:House|Senate|Congress)|President of the United States|"
    r"Vice President of the United States|United States federal judge|"
    r"judge of the United States|Treasurer of the United States|White House|"
    r"Speaker of the United States House", re.IGNORECASE)
STATE_LOCAL_POSITION_RE = re.compile(
    r"member of the .*(?:House of Representatives|Senate|Assembly|House of Delegates|Legislature|"
    r"General Court)|state senator|state representative|state legislator|mayor of|"
    r"Governor of|Lieutenant Governor of|Secretary of State of|Attorney General of|"
    r"Treasurer of|Comptroller|Auditor|council|alderman|sheriff|county|commissioner|"
    r"district attorney|borough president|school board", re.IGNORECASE)
LEGISLATOR_POSITION_RE = re.compile(
    r"member of the .*(?:House of Representatives|Senate|Assembly|House of Delegates|Legislature|"
    r"General Court)|state senator|state representative|state legislator", re.IGNORECASE)


def wikidata_convicted(sparql: Sparql) -> list[dict]:
    """Personnes américaines condamnées (P1399) ayant un mandat ou politiciennes."""
    q = """SELECT ?item ?itemLabel ?title ?partyLabel ?posLabel ?date WHERE {
      ?item wdt:P1399 ?conv ; wdt:P27 wd:Q30 .
      { ?item wdt:P39 [] } UNION { ?item wdt:P106 wd:Q82955 }
      OPTIONAL { ?item wdt:P39 ?pos . ?pos rdfs:label ?posLabel . FILTER(LANG(?posLabel) = "en") }
      OPTIONAL { ?item wdt:P102 ?party . ?party rdfs:label ?partyLabel .
                 FILTER(LANG(?partyLabel) = "en") }
      OPTIONAL { ?a schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> ;
                 schema:name ?title . }
      OPTIONAL { ?item p:P1399/pq:P585 ?date . }
      OPTIONAL { ?item rdfs:label ?itemLabel . FILTER(LANG(?itemLabel) = "en") }
    }"""
    people: dict[str, dict] = {}
    for row in sparql.query(q):
        p = people.setdefault(row["item"], {
            "item": row["item"].rsplit("/", 1)[-1], "label": row.get("itemLabel", ""),
            "title": row.get("title", ""), "parties": [], "positions": [], "years": []})
        for key, field in (("partyLabel", "parties"), ("posLabel", "positions")):
            if row.get(key) and row[key] not in p[field]:
                p[field].append(row[key])
        if row.get("date", "")[:4].isdigit():
            p["years"].append(int(row["date"][:4]))
    return list(people.values())


# --------------------------------------------------------------------------
# Klarner (Harvard Dataverse)
# --------------------------------------------------------------------------

def klarner_seats(cache_dir: Path, verbose: bool = True) -> list[dict]:
    """Sièges D / R / autres (deux chambres) par État et par année, 1937-2011."""
    import openpyxl  # dépendance optionnelle, seulement pour cette source

    dest = cache_dir / KLARNER_FILE
    if not dest.exists():
        s = _session()
        files = _get(s, f"{DATAVERSE}/api/datasets/:persistentId/versions/:latest/files",
                     params={"persistentId": KLARNER_DOI}).json()["data"]
        file_id = next(f["dataFile"]["id"] for f in files
                       if f["dataFile"]["filename"] == KLARNER_FILE)
        if verbose:
            print(f"  téléchargement Klarner ({KLARNER_FILE})", file=sys.stderr)
        dest.write_bytes(_get(s, f"{DATAVERSE}/api/access/datafile/{file_id}").content)
    wb = openpyxl.load_workbook(dest, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    it = ws.iter_rows(values_only=True)
    head = list(next(it))
    idx = {h: i for i, h in enumerate(head)}

    def num(row, col):
        v = row[idx[col]]
        return int(v) if isinstance(v, (int, float)) else None

    out = []
    for row in it:
        state, year = row[idx["state"]], num(row, "year")
        if not state or not year:
            continue
        parts = [num(row, f"{ch}_{p}_in_sess") for ch in ("sen", "hs") for p in ("dem", "rep", "ind")]
        if any(v is None for v in parts[:2] + parts[3:5]):
            continue  # chambre sans effectifs partisans (Nebraska, données manquantes)
        d = parts[0] + parts[3]
        r = parts[1] + parts[4]
        o = (parts[2] or 0) + (parts[5] or 0)
        if d + r:
            out.append({"etat": state, "annee": year, "democrates": d, "republicains": r,
                        "autres": o})
    return out


def compare_seats(wiki: list[dict], klarner: list[dict]) -> dict:
    """Concordance entre les sièges tirés de Wikipédia et ceux de Klarner."""
    w = {(r["etat"], r["annee"]): r for r in wiki}
    diffs, share_diffs = [], []
    for k in klarner:
        x = w.get((k["etat"], k["annee"]))
        if not x:
            continue
        diffs.append(abs(x["democrates"] - k["democrates"]) + abs(x["republicains"] - k["republicains"]))
        sw = x["democrates"] / (x["democrates"] + x["republicains"])
        sk = k["democrates"] / (k["democrates"] + k["republicains"])
        share_diffs.append(abs(sw - sk) * 100)
    n = len(diffs)
    if not n:
        return {"etat_annees_comparees": 0}
    share_diffs.sort()
    return {
        "etat_annees_comparees": n,
        "identiques": sum(d == 0 for d in diffs),
        "ecart_de_5_sieges_ou_moins_pct": round(100 * sum(d <= 5 for d in diffs) / n, 1),
        "ecart_median_part_D_points": round(share_diffs[n // 2], 2),
        "ecart_part_D_inferieur_a_2_points_pct": round(
            100 * sum(s < 2 for s in share_diffs) / n, 1),
    }


# --------------------------------------------------------------------------
# Ministère de la Justice (Public Integrity Section)
# --------------------------------------------------------------------------

# Au moins 5 années consécutives sur une ligne, seules ou après « Federal Officials »
# (mise en page du rapport 1983).
YEARS_LINE_RE = re.compile(r"((?:(?:19|20)\d\d\s+){4,}(?:19|20)\d\d)\b")


def pdf_text(path: Path) -> str:
    if shutil.which("pdftotext"):
        return subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True,
                              text=True, check=False).stdout
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text(layout=True) or "" for page in pdf.pages)


def parse_doj_table(text: str) -> dict[int, dict[str, int]]:
    """Année -> {« etat »: condamnés, « local »: condamnés} d'après un rapport annuel."""
    out: dict[int, dict[str, int]] = defaultdict(dict)
    years: list[int] = []
    section = None
    for line in text.splitlines():
        if re.search(r"\bTABLE\b", line):
            years, section = [], None
            continue
        m = YEARS_LINE_RE.search(line)
        if m:
            years = [int(y) for y in m.group(1).split()]
        low = line.strip().lower()
        if re.match(r"^state officials\b", low):
            section = "etat"
        elif re.match(r"^local officials\b", low):
            section = "local"
        elif re.match(r"^(federal officials|others involved|private citizens|totals?)\b", low):
            section = None
        elif section and years and re.match(r"^[-–\s]*convicted\b", low):
            nums = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", line)
                    if n.replace(",", "")]
            if len(nums) >= len(years):
                for y, n in zip(years, nums):
                    out[y].setdefault(section, n)
    return {y: v for y, v in out.items() if "etat" in v and "local" in v}


def doj_convictions(cache_dir: Path, verbose: bool = True) -> dict[int, dict[str, int]]:
    """Série annuelle 1974-2023 ; un rapport récent l'emporte sur un ancien."""
    s = _session()
    series: dict[int, dict[str, int]] = {}
    for report_year, url in sorted(DOJ_REPORTS.items(), reverse=True):
        dest = cache_dir / f"doj_pin_{report_year}.pdf"
        if not dest.exists():
            if verbose:
                print(f"  téléchargement du rapport PIN {report_year}", file=sys.stderr)
            dest.write_bytes(_get(s, url).content)
        for y, v in parse_doj_table(pdf_text(dest)).items():
            series.setdefault(y, {**v, "rapport": report_year})
    return dict(sorted(series.items()))
