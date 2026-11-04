# Démocrates vs républicains condamnés — listes Wikipédia

`compter_partis.py` récupère la page Wikipédia
[Lists of American state and local politicians convicted of crimes](https://en.wikipedia.org/wiki/Lists_of_American_state_and_local_politicians_convicted_of_crimes)
**et toutes les sous-listes vers lesquelles elle renvoie**, extrait chaque
personne citée et compte combien sont démocrates, républicaines, d'un autre
parti, ou de parti non déterminé.

## Installation

```bash
pip install -r requirements.txt
```

## Utilisation

```bash
python compter_partis.py                         # rapport + politiciens_condamnes.csv
python compter_partis.py --json resume.json      # + résumé JSON
python compter_partis.py --strict                # sans les déductions par mot-clé
python compter_partis.py --cache-dir cache/      # garde les pages pour relancer hors ligne
```

| Option | Rôle |
|---|---|
| `--csv FICHIER` | détail de chaque entrée (défaut : `politiciens_condamnes.csv`) |
| `--json FICHIER` | résumé chiffré, détail par page, pages en échec |
| `--strict` | ne compte que les partis indiqués explicitement |
| `--max-depth N` | profondeur de suivi des sous-listes (défaut : 2) |
| `--delay S` | pause entre deux requêtes à Wikipédia (défaut : 0,5 s) |
| `--cache-dir DOSSIER` | met en cache les pages téléchargées |
| `--start TITRE` | autre page de départ |

Code de sortie : `0` si tout s'est bien passé, `2` si une sous-liste n'a pas pu
être téléchargée (le décompte est alors incomplet et le rapport le signale),
`1` si la page de départ elle-même est inaccessible.

## Fonctionnement

1. **Téléchargement** via l'API officielle MediaWiki (`action=parse`), avec un
   User-Agent identifiable, une pause entre les requêtes, la prise en compte
   des redirections et des reprises en cas d'erreur 429/5xx ou `maxlag`.
2. **Parcours** : depuis la page d'index, le script suit les liens dont le
   titre commence par « List of … convicted … ». Il exclut les listes
   fédérales et ignore les sections *See also*, *References*, *External links*,
   ainsi que les bandeaux de navigation. Aujourd'hui, l'index renvoie vers 17
   listes **par décennie** (années 1850 à 2020), elles-mêmes classées par État.
3. **Extraction** des entrées : puces `<li>` (sans leurs sous-listes) et
   lignes des tableaux `wikitable`. Les sous-puces qui détaillent la
   condamnation de la personne parente (« John McGee (R): » puis « Found
   guilty of… ») ne sont pas comptées comme des personnes en plus.
4. **Détection du parti**, de la méthode la plus fiable à la moins fiable
   (colonne `methode` du CSV) :
   - `marqueur` : `(D)`, `(R)`, `(R-TX)`, `(D–Chicago)`, `(Democrat)`,
     `(Republican)`, `(DFL)`, `(populist)`, `(PNP)`… placé derrière le nom.
     `(D.C.)`, `(R.I.)`, `(?)` ou `(-)` ne sont pas pris pour des partis ;
   - `colonne` : colonne *Party* d'un tableau ;
   - `titre` : entrée rangée sous un titre « Democrats » ou « Republicans » ;
   - `mot-clé` : « Democratic »/« Republican » ailleurs dans le texte
     (désactivé par `--strict`).
   Le DFL du Minnesota est compté comme démocrate. Indépendants, Working
   Families, Green-Rainbow, partis de Porto Rico (PNP, PPD) et des Mariannes
   du Nord (Covenant) vont dans « Autre ».
5. **Plusieurs personnes dans une puce** : on compte chaque personne marquée
   *avant* le verbe principal (« X (D) and Y (R) were convicted » → 2
   condamnés). Celles nommées après le verbe ne sont pas comptées : dans
   « Looper (R) was convicted of the murder of Senator Burks (D) », Burks est
   la victime.
6. **Dédoublonnage** : une personne présente dans plusieurs listes n'est
   comptée qu'une fois. L'identité est l'article Wikipédia lié au nom, sinon
   le nom et l'État. Une entrée sans parti n'est jamais fusionnée. Le CSV
   garde toutes les lignes, avec les colonnes `article` et `compte_dans_total`.

## Limites à connaître

- **Condamnés, pas seulement inculpés.** La page recense des politiciens
  *condamnés* (« convicted »). Une personne seulement inculpée puis acquittée
  n'y figure normalement pas : le script compte donc des condamnations.
- **Ce que dit la liste, pas une vérification.** Le script reprend le parti
  et l'inclusion tels qu'ils sont écrits sur Wikipédia. Quelques entrées
  décrivent une personne inculpée mais pas (encore) condamnée, voire une
  personne qui s'est suicidée avant procès (opération « Rocky Top »).
- **Heuristique.** Les règles ci-dessus ont été vérifiées à la main sur les
  vraies pages, mais un nom sans lien peut garder sa fonction (« State
  Senator John Doe »). Deux mentions sans lien d'une même personne, écrites
  différemment, peuvent alors rester séparées. Vérifiez dans le CSV les
  lignes `Indéterminé`.
- **Pas une mesure de la criminalité des partis.** Les listes Wikipédia sont
  incomplètes et inégales selon les États et les époques ; elles mélangent
  plus d'un siècle de vie politique locale.

## Tests

```bash
python -m unittest discover -s tests -v
```
