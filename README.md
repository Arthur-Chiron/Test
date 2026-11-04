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
   ainsi que les bandeaux de navigation.
3. **Extraction** des entrées : puces `<li>` (sans leurs sous-listes) et
   lignes des tableaux `wikitable`.
4. **Détection du parti**, de la méthode la plus fiable à la moins fiable
   (colonne `methode` du CSV) :
   - `marqueur` : `(D)`, `(R)`, `(R-TX)`, `(D–Chicago)`, `(Democrat)`,
     `(Republican)`, `(DFL)`… placé derrière le nom. `(D.C.)` ou `(R.I.)` ne
     sont pas pris pour des partis ;
   - `colonne` : colonne *Party* d'un tableau ;
   - `titre` : entrée rangée sous un titre « Democrats » ou « Republicans » ;
   - `mot-clé` : « Democratic »/« Republican » ailleurs dans le texte
     (désactivé par `--strict`).
   Le DFL du Minnesota est compté comme démocrate. Indépendants, libertariens,
   whigs, etc. vont dans « Autre ».
5. **Dédoublonnage** : une personne présente dans plusieurs listes n'est
   comptée qu'une fois. Le CSV garde toutes les lignes, avec une colonne
   `compte_dans_total`.

## Limites à connaître

- **Condamnés, pas seulement inculpés.** La page recense des politiciens
  *condamnés* (« convicted »). Une personne seulement inculpée puis acquittée
  n'y figure normalement pas : le script compte donc des condamnations.
- **Heuristique.** Une puce = une personne, et c'est le premier marqueur de
  parti qui compte. Une puce citant plusieurs personnes ne compte qu'une
  fois. Les homonymes sont fusionnés. Vérifiez dans le CSV les lignes
  `Indéterminé` et celles détectées par `mot-clé`.
- **Pas une mesure de la criminalité des partis.** Les listes Wikipédia sont
  incomplètes et inégales selon les États et les époques ; elles mélangent
  plus d'un siècle de vie politique locale.
- **Pas encore lancé sur la vraie page.** Le script a été écrit dans un
  environnement où Wikipédia n'était pas accessible. L'analyse HTML est
  testée sur des pages reproduisant le format de l'API (anciens et nouveaux
  titres de section, tableaux, notes de bas de page, navbox), mais pas sur le
  contenu réel. Au premier lancement, contrôlez le CSV.

## Tests

```bash
python -m unittest discover -s tests -v
```
