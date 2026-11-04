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

## Base exhaustive et comparaison au nombre d'élus

```bash
python collecte_exhaustive.py --cache-dir cache/   # ~150 requêtes, 20-40 min la 1re fois
python graphiques.py --date 2026-11-04             # graphiques + analyse
```

`collecte_exhaustive.py` élargit la base au-delà des listes par décennie, en
utilisant uniquement Wikipédia :

| Source | Contenu |
|---|---|
| 17 listes par décennie | élus d'États et locaux condamnés pour des faits commis en fonction, avec leur parti |
| 3 listes « … officials convicted of federal corruption offenses » | élus d'États, locaux et des territoires condamnés pour corruption par la justice fédérale (tableaux sans parti) |
| arbre de catégories « American politicians convicted of crimes » | tous les articles de politiciens condamnés ; on ne garde que ceux qui ont exercé un mandat d'État ou local et aucun mandat fédéral |
| pages « Political party strength in <État> » | sièges démocrates et républicains de chaque parlement d'État, année par année |

Une personne présente dans plusieurs sources n'est comptée qu'une fois
(identité = article Wikipédia). Son parti vient du marqueur de la liste
(« (D) », « (R) ») quand elle y figure. Sinon, il vient de son article :
catégories « Democratic Party members of … » et champ `party` de l'infobox.
Le script vérifie que les deux méthodes concordent sur les personnes
présentes partout (résultat dans `collecte.json`).

`graphiques.py` compare les condamnés au **nombre d'élus de chaque parti**.
Si un parti détient plus de sièges, il est normal qu'il compte plus de
condamnés. Deux mesures :

- **attendu si même taux** : pour chaque condamné, on prend la part de sièges
  démocrates du parlement de son État pendant sa décennie. La somme donne le
  nombre de démocrates attendu si les deux partis avaient le même taux de
  condamnation. On le compare au nombre observé (écart exprimé en
  écarts-types) ;
- **taux par siège** : parlementaires d'États condamnés pour 1 000 sièges
  détenus par leur parti, décennie par décennie.

Sorties dans `resultats/` : `base_exhaustive.csv`,
`sieges_parlements_etats.csv`, `collecte.json`, `analyse.json`, `analyse.md`
(tous les chiffres sous forme de tableaux) et `graphiques/*.png`.

**Limites propres à cette comparaison.** Le seul effectif d'élus par parti
disponible sur Wikipédia est celui des parlements d'États. Il sert de
référence aussi pour les élus locaux, dont beaucoup sont élus sans étiquette.
Wikipédia ne recense qu'une petite partie des condamnations réelles, et ses
contributeurs couvrent certains États et certaines affaires bien plus que
d'autres. Sources consultées mais bloquées dans l'environnement de
développement : Wikidata, Harvard Dataverse (données de Klarner sur la
composition des parlements), NCSL, ministère de la Justice (rapports de la
Public Integrity Section), Ballotpedia.

## Utilisation de compter_partis.py

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
