# Kilomètres et D+ du bilan hebdomadaire — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Afficher `≈ 36 km · ≈ 450 m D+` sous la durée du bilan de la semaine.

**Architecture:** Claude renseigne `d_plus_m` par séance ; la valeur est stockée et lue par l'API et par la PWA (Turso). Les km sont calculés dans l'interface par une fonction pure, commune aux deux.

**Tech Stack:** Python (Pydantic, SQLModel, pytest), Svelte 5 / TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-11-25-bilan-km-dplus-design.md`

## Global Constraints

- `d_plus_m: int | None`, ≥ 0, défaut `None` ; `SCHEMA_VERSION = 4`, `KNOWN_SCHEMA = 4`.
- Textes et commentaires en français ; affichage `≈ 36 km · ≈ 450 m D+`.
- Km arrondis à l'unité, vélo exclu, séances faites ou non comptées. D+ total nul ou absent : masqué.
- Aucun échec de validation si Claude ne renseigne pas `d_plus_m`.
- Jamais d'échec visible du bilan si zones ou statistiques ne se chargent pas.
- Ni envoi à Garmin, ni calendrier, ni carte de séance.

## Review Focus

- Zones d'allure absentes : pas de km faux, mais le D+ reste affiché (tâches 2 et 3).
- Semaine de vélo uniquement : ni km ni D+, pas de « ≈ 0 km » (tâches 2 et 3).
- Proposition en attente enregistrée avant la mise à jour (sans `d_plus_m`) : s'applique sans erreur (tâche 1).
- Sorties trail sans distance ou durée, ou vieilles de plus de 8 semaines : ignorées (tâche 2).
- Séance à D+ modifiée par Claude sans D+ : l'ancienne valeur est effacée (tâche 1).

---

### Task 1: D+ prescrit par séance, de Claude à la lecture

**Files:**
- Modify: `coach/llm/schemas.py`, `coach/llm/prompts.py`, `coach/plan/models.py`, `coach/plan/repo.py`, `coach/services/garmin_export.py`, `coach/api/app.py`
- Modify: `web/src/lib/api.ts`, `web/src/lib/turso/{db,reads,mappers}.ts`, `tests/mobile_fixtures.py`, `web/src/lib/turso/__fixtures__/*` (régénérées)
- Test: `tests/llm/test_schemas.py`, `tests/llm/test_prompts.py`, `tests/plan/test_repo.py`, `tests/services/test_garmin_export.py`, `tests/api/test_app.py`, `web/src/lib/turso/reads.test.ts`

**Interfaces:**
- Produces: `SessionSpec.d_plus_m: int | None = Field(default=None, ge=0)` ; `Session.d_plus_m: int | None = None` ; clé `d_plus_m` de `_session_dict` ; TS `Session.d_plus_m?: number | null` ; constantes `D_PLUS_RULE` et `NO_D_PLUS_RULE` dans `prompts.py`.

- [ ] **Step 1: Écrire les tests qui échouent** (imports et fixtures locales de chaque fichier)

```python
# schémas
def test_session_d_plus_optional_and_positive():
    assert make_session().d_plus_m is None
    with pytest.raises(ValidationError):
        SessionSpec(**{**make_session().model_dump(), "d_plus_m": -1})

def test_session_d_plus_round_trip():
    spec = make_session().model_copy(update={"d_plus_m": 600})
    assert Session.from_spec(spec, cycle_id=1).to_spec().d_plus_m == 600

# prompts
def test_generation_prompt_asks_d_plus_only_for_hilly_goals():
    def gen(d):
        return build_generation_prompt(make_cycle(), [make_goal(d_plus_m=d)], [], ZONES, [], n_weeks=8, gpx_texts=[])
    assert D_PLUS_RULE in gen(2000) and NO_D_PLUS_RULE not in gen(2000)
    assert NO_D_PLUS_RULE in gen(0) and D_PLUS_RULE not in gen(0)

def test_adjustment_prompt_asks_d_plus():
    adj = build_adjustment_prompt(make_cycle(), [make_goal(d_plus_m=2000)], [], ZONES, 1, [], [], [], [])
    assert D_PLUS_RULE in adj

def test_session_line_shows_d_plus():
    s = _db(1)
    s.d_plus_m = 600
    assert _session_line(s).endswith(" | D+ 600 m")
    s.d_plus_m = None
    assert "D+" not in _session_line(s)
```

Autres tests, mêmes conventions :

| Test | Assertion |
|---|---|
| `test_modify_replaces_d_plus` (garmin_export) | `modify(session_w3.id, d_plus_m=600)` appliqué : 600 en base |
| `test_modify_without_d_plus_clears_it` | 600 en base, `modify(session_w3.id)` appliqué : `None` |
| `test_old_proposal_without_d_plus_applies` | clé `d_plus_m` retirée du JSON enregistré de la proposition : elle finit `accepted` |
| `test_plan_exposes_d_plus` (api) | séance à 600 : `GET /api/plan` donne 600 |
| `test_migrates_v3_adds_d_plus` (repo) | `DROP COLUMN d_plus_m` et version 3, puis `make_engine` : colonne présente, version 4 |
| `reads.test.ts` | la séance à laquelle `tests/mobile_fixtures.py` donne 600 est lue avec `d_plus_m === 600` |

Dans `tests/plan/test_repo.py`, les deux assertions `{"v": 3}` deviennent `{"v": SCHEMA_VERSION}`.

- [ ] **Step 2: Vérifier l'échec** — `python -m pytest tests/llm tests/plan tests/services/test_garmin_export.py tests/api -q` : les nouveaux tests échouent.

- [ ] **Step 3: Implémenter**
  - Champ dans `SessionSpec` et `Session`, `to_spec`, `from_spec` ; `"d_plus_m"` dans la liste copiée par `modify` (`garmin_export.py`) ; `_session_dict`.
  - `_migrate` : `add_columns("session", {"d_plus_m": "INTEGER"})` ; version 4 et commentaire dans `repo.py` et `db.ts` ; colonne dans `REQUIRED_COLUMNS.session`, `SESSION_COLS` et `sessionDict` (`num(r.d_plus_m)`).
  - Les deux prompts, juste après `_cycle_rules` : `D_PLUS_RULE` si `any(g.d_plus_m > 0 for g in goals)`, sinon `NO_D_PLUS_RULE`.

```python
D_PLUS_RULE = (
    "Dénivelé : pour chaque séance de course qui travaille le dénivelé (surtout les sorties longues et les côtes), "
    "indique le D+ total prévu dans d_plus_m (en mètres) et mentionne-le dans la description, avec une progression "
    "adaptée à la course ; laisse d_plus_m à null pour les autres séances et le vélo."
)
NO_D_PLUS_RULE = "Dénivelé : laisse d_plus_m à null pour toutes les séances."
```

  - `_session_line` : suffixe ` | D+ 600 m`, seulement si la valeur est non nulle.
  - Régénérer les fixtures : `python -m tests.mobile_fixtures`.

- [ ] **Step 4: Vérifier** — `python -m pytest -q`, puis dans `web` `npx vitest run src/lib/turso` : tout passe.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: D+ prescrit par séance"`

### Task 2: Calcul des km et du D+ de la semaine

**Files:**
- Create: `web/src/lib/weekVolume.ts`
- Test: `web/src/lib/weekVolume.test.ts`

**Interfaces:**
- Consumes: `Session.d_plus_m`, `Zones`, `StatActivity` de `api.ts` ; `addDays` de `dates.ts`.
- Produces:
  - `trailPace(activities: StatActivity[], today: string): number | null` — s/km, temps total / distance totale des sorties de famille `trail` avec `addDays(today, -56) <= date <= today`.
  - `weekKm(sessions: Session[], zones: Zones | null, trail: number | null): number | null` — entier, `null` si incalculable ou nul.
  - `weekDPlus(sessions: Session[]): number | null` — `null` si nul.
  - `volumeLine(km: number | null, dPlus: number | null): string`.

- [ ] **Step 1: Écrire les tests qui échouent** — un `test` par ligne, avec `zones.pace` = récup `[360, 400]`, EF `[340, 380]`, marathon `[300, 320]`, seuil `[270, 290]`, VMA `[240, 260]` :

| Cas | Attendu |
|---|---|
| 5 × 1000 m, zones `null` | `weekKm` 5 |
| 3600 s en EF ; 3600 s en Z2 | 10 ; 10 |
| 3800 s en Z1 ; 3100 s en Z3 ; 2800 s en Z4 ; 2500 s en Z5 | 10 chacun |
| sans zone : `recovery` 3800 s ; `warmup` 3600 s | 10 ; 10 |
| `hr`, D+ 600, 3600 s en Z2 : trail 450 ; trail `null` | 8 ; 10 |
| `pace`, D+ 600, 3600 s en EF, trail 450 | 10 |
| zones `null`, 3600 s en EF | `null` |
| zones `null`, `hr`, D+ 600, 3600 s, trail 450 | 8 |
| deux séances de 5400 m (arrondi du total) | 11 |
| vélo seul, 3600 s, D+ 300 | `weekKm` et `weekDPlus` : `null` |
| D+ 600, `null`, 150 ; tous `null` ou 0 | `weekDPlus` 750 ; `null` |
| trail (3600 s, 8000 m) et (5400 s, 12000 m) | `trailPace` 450 |
| route, distance `null` ou 0, durée `null`, J-57, liste vide | `trailPace` `null` |
| trail à J-56 | comptée |
| `volumeLine(36, 450)` ; `(36, null)` ; `(null, 450)` ; `(null, null)` | `≈ 36 km · ≈ 450 m D+` ; `≈ 36 km` ; `≈ 450 m D+` ; chaîne vide |

- [ ] **Step 2: Vérifier l'échec** — `npx vitest run src/lib/weekVolume.test.ts` : module introuvable.
- [ ] **Step 3: Implémenter** — Z1→récup, Z2→EF, Z3→marathon, Z4→seuil, Z5→VMA ; allure = moyenne des deux bornes ; l'allure trail remplace celle de toutes les étapes en durée d'une séance `hr` dont `d_plus_m > 0`.
- [ ] **Step 4: Vérifier** — même commande : tout passe.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(web): estimation des km et du D+ de la semaine"`

### Task 3: Affichage dans le bilan

**Files:**
- Modify: `web/src/routes/Week.svelte`
- Test: `web/src/routes/Week.test.ts`

**Interfaces:**
- Consumes: les quatre fonctions de la tâche 2 ; `api.zones()`, `api.statsActivities()`, `cached`.

- [ ] **Step 1: Écrire les tests qui échouent** — `mock` répond aussi à `/api/zones` (`null` par défaut) et `/api/stats/activities` (`{ activities: [] }`). Dans la région « Bilan de la semaine » :
  - zones de la tâche 2, une séance EF de 3600 s, D+ 450, `pace` : contient `≈ 10 km · ≈ 450 m D+` ;
  - même séance sans D+ : contient `≈ 10 km`, pas `D+`, et `/api/stats/activities` n'est jamais appelée ;
  - zones `null`, D+ 450 : contient `≈ 450 m D+`, pas `km` ;
  - séance `hr`, D+ 450, Z2 3600 s, sortie trail récente à 450 s/km : contient `≈ 8 km` ;
  - `/api/zones` en 500 : `1/2 séances faites` reste affiché, aucun bandeau d'erreur ;
  - séance de vélo seule : ne contient pas `≈`.
- [ ] **Step 2: Vérifier l'échec** — `npx vitest run src/routes/Week.test.ts`.
- [ ] **Step 3: Implémenter** — zones lues au chargement et à chaque `version` ; activités lues seulement si une séance `hr` du plan a du D+ ; mêmes clés de cache que les autres lecteurs de ces deux routes s'il y en a ; échecs ignorés (`.catch(() => {})`). Après la ligne de durée : `{#if line}<p class="meta">{line}</p>{/if}`.
- [ ] **Step 4: Vérifier** — dans `web` : `npm test` et `npm run build` ; à la racine : `python -m pytest -q` ; tout passe. Contrôler le bloc dans le navigateur, en largeur bureau et mobile.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(web): km et D+ prévus dans le bilan de la semaine"`
