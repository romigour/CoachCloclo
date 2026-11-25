# Statistiques en sous-pages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ranger Statistiques en cinq sous-pages adressables et ajouter charge, prédicteur, FC à allure donnée et constats.

**Architecture:** `Stats.svelte` reste montée comme coquille (données, filtres, onglets) et affiche une vue selon l'adresse. Tous les calculs et toutes les phrases sont des fonctions pures de `web/src/lib/stats/`. Aucune nouvelle donnée serveur.

**Tech Stack:** Svelte 5, TypeScript, ECharts, vitest.

**Spec:** `docs/superpowers/specs/2026-11-25-stats-sous-pages-design.md`

## Global Constraints

- Aucun changement Python, de schéma, ni de `web/src/lib/turso/` ; aucune dépendance ajoutée.
- Clés de sous-page : `overview`, `progress`, `load`, `intensity`, `races` ; `#/stats` = `overview`.
- Course = familles `run` et `trail`. Dates ISO, calculs en UTC, semaines du lundi au dimanche.
- Données insuffisantes : message explicite, jamais de chiffre. Commentaires et textes en français, tutoiement.
- Tests depuis `web/` : `npm ci` une fois, puis `npx vitest run <fichier>` ; fin : `npm test`, `npm run build`, `npm run build:mobile`.
- Chaque commit finit par `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Zones absentes ou non `karvonen` → seuls les blocs de charge affichent leur message (tâches 1 et 6).
2. Filtre vélo puis onglet Progression → les courses s'affichent, le filtre vélo revient sur Aperçu (tâche 5).
3. Filtre sport ou période changé → forme du jour et ACWR identiques (tâche 6).
4. Adresse inconnue ou lien direct vers une sous-page au démarrage → bonne vue, mobile compris (tâche 4).
5. Séances sans FC, FC repos ≥ FC max → aucune charge, aucun `NaN` affiché (tâche 1).

---

### Task 1: Charge

**Files:** Create `web/src/lib/stats/load.ts`, `web/src/lib/stats/load.test.ts`

**Interfaces — Produces:**
- `type HrRange = { rest: number; max: number }`
- `hrRange(zones: Zones | null): HrRange | null` (`max = Z5[1]`, `rest = 2 × Z1[0] − Z5[1]` ; null sans `karvonen` ou si `!(0 < rest < max)`)
- `trimp(a: StatActivity, hr: HrRange): number | null`
- `type FitnessPoint = { date: string; ctl: number; atl: number; tsb: number }`
- `fitnessSeries(all: StatActivity[], hr: HrRange, today: string): FitnessPoint[]` (tout l'historique)
- `visibleFitness(s: FitnessPoint[], p: Period): FitnessPoint[]` (sans les 42 premiers jours de la série)
- `acwr(all: StatActivity[], hr: HrRange, today: string): number | null`
- `weeklyRamp(acts: StatActivity[], today: string): number | null` (relatif, 0.15 = +15 %)
- `hrCoverage(all: StatActivity[], today: string): { missing: number; missingShare: number }` (42 derniers jours, part en durée)
- `RAMP_ALERT = 0.15`, `MISSING_HR_ALERT = 0.3`

- [ ] **Step 1: Tests** (les noms de séries en français sont des fixtures à construire dans le test)

```ts
const HR = { rest: 50, max: 190 };
expect(hrRange({ pace: null, hr: { Z1: [120, 134], Z5: [176, 190] }, source: ["karvonen"] })).toEqual(HR);
expect(hrRange({ pace: null, hr: { Z1: [120, 134], Z5: [176, 190] }, source: [] })).toBeNull();
expect(hrRange({ pace: null, hr: { Z1: [190, 190], Z5: [190, 190] }, source: ["karvonen"] })).toBeNull();
expect(hrRange(null)).toBeNull();
expect(trimp(act({ duration_s: 3600, avg_hr: 150 }), HR)).toBeCloseTo(108.1, 1);
expect(trimp(act({ avg_hr: null }), HR)).toBeNull();
expect(trimp(act({ duration_s: null }), HR)).toBeNull();
expect(trimp(act({ avg_hr: 40 }), HR)).toBe(0); // x borné
// s : un jour de charge T puis un jour vide
const T = 108.095;
expect(s[0].ctl).toBeCloseTo(T / 42, 2);
expect(s[0].atl).toBeCloseTo(T / 7, 2);
expect(s[1].atl).toBeCloseTo((T / 7) * (6 / 7), 2);
expect(s[1].tsb).toBeCloseTo(s[1].ctl - s[1].atl, 6);
expect(fitnessSeries([], HR, "2026-01-01")).toEqual([]);
expect(visibleFitness(serie100Jours, periodeEntiere)[0].date).toBe(serie100Jours[42].date);
expect(acwr(chargeConstante28Jours, HR, today)).toBeCloseTo(1, 6);
expect(acwr(historique27Jours, HR, today)).toBeNull(); // historique de moins de 28 jours
// mercredi 2026-11-25 : semaine en cours ignorée ; quatre semaines de 4 h puis une de 5 h
expect(weeklyRamp(acts, "2026-11-25")).toBeCloseTo(0.25, 6);
expect(weeklyRamp([], "2026-11-25")).toBeNull();
// une séance d'1 h sans FC, une d'1 h avec FC
expect(hrCoverage(deuxSeances, today)).toEqual({ missing: 1, missingShare: 0.5 });
// activité datée après today : absente de fitnessSeries
```

- [ ] **Step 2:** `npx vitest run src/lib/stats/load.test.ts` → FAIL (module absent)
- [ ] **Step 3: Implémenter** : `min × x × 0.64 × exp(1.92 x)`, `v += (charge − v) / N` (42, 7).
- [ ] **Step 4:** même commande → PASS
- [ ] **Step 5: Commit** `feat(web): calcul de la charge d'entraînement`

### Task 2: Prédicteur et FC à allure donnée

**Files:** Create `web/src/lib/stats/predict.ts`, `predict.test.ts` ; Modify `web/src/lib/stats/running.ts`, `running.test.ts`

**Interfaces — Produces:**
- `type Reference = { category: DistanceCategory; timeS: number; date: string; source: "race" | "record" }`
- `references(all: StatActivity[], records: PersonalRecord[], today: string): Reference[]` (365 jours au plus, jamais de trail)
- `type Prediction = { category: DistanceCategory; timeS: number; from: Reference }`
- `predictions(refs: Reference[]): Prediction[]` (ordre 5k, 10k, half, marathon)
- dans `running.ts` : `flatRuns(acts)` extrait de `aerobicEfficiency` (mêmes critères) ;
  `hrAtPace(acts): { paceSKm: number; from: number; to: number; count: number } | null` (bpm arrondis)
- dans `running.ts` : `rollingMean(points: { date: string; value: number }[], n = 5)` (vide si moins de `n` points)

- [ ] **Step 1: Tests**

```ts
// référence 10 km en 3000 s
expect(byCat("5k").timeS).toBeCloseTo(1438.9, 0);
expect(byCat("10k").timeS).toBe(3000);
expect(byCat("half").timeS).toBeCloseTo(6619, -1);
expect(byCat("marathon")).toBeUndefined(); // rapport 4,22 > 4
// références 5 km et semi : le 10 km part du 5 km (ln 2 < ln 2,11)
expect(p10.from.category).toBe("5k");
expect(predictions([])).toEqual([]);
// 9 sorties à 330 s/km, FC 158,158,158,154,154,154,149,149,149
expect(hrAtPace(nine)).toEqual({ paceSKm: 330, from: 158, to: 149, count: 9 });
expect(hrAtPace(nine.slice(1))).toBeNull();
expect(rollingMean(quatrePoints)).toEqual([]);
expect(rollingMean(sixPoints123456).map((p) => p.value)).toEqual([3, 4]); // datés du dernier point de la fenêtre
```

Cas à assérer aussi : même distance → référence la plus récente ; 366 jours exclue, 365 gardée ; date null, trail et temps ≤ 0 exclus ; temps officiel préféré au temps montre ; records `1k`, `1mile`, `longest_run` ignorés ; sortie à 345 s/km non comptée ; médiane 332 → `paceSKm` 330 ; 10 sorties → tiers de 3.

- [ ] **Step 2:** `npx vitest run src/lib/stats/predict.test.ts src/lib/stats/running.test.ts` → FAIL
- [ ] **Step 3: Implémenter** Riegel `t × (cible / ref) ** 1.06` avec `CATEGORY_M` ; proximité `|ln(cible / ref)|`.
- [ ] **Step 4:** même commande → PASS (tests existants compris)
- [ ] **Step 5: Commit** `feat(web): prédicteur de temps et FC à allure donnée`

### Task 3: Intensité et phrases

**Files:** Create `web/src/lib/stats/intensity.ts`, `intensity.test.ts`, `insights.ts`, `insights.test.ts`

**Interfaces — Consumes:** `zoneDistribution`, `trendLine`, types des tâches 1 et 2.
**Produces:**
- `type Split = { easy: number; moderate: number; hard: number }` ; `split(zones: number[]): Split | null` (Z1-2, Z3, Z4-5, parts de 0 à 1)
- `monthlySplit(acts: StatActivity[], p: Period): { month: string; split: Split | null }[]` (tous les mois de `p`)
- `insights.ts`, toutes `string | null` : `efficiencyText(changePct: number | null)`, `hrAtPaceText(r: ReturnType<typeof hrAtPace>)`, `vo2Text(values: number[])`, `longestText(list: { month: string; km: number }[])`, `fitnessText(p: FitnessPoint | undefined)`, `acwrText(v: number | null)`, `rampText(v: number | null)`, `volumeText(deltaHours: number | null)`, `splitText(s: Split | null)`, `trailText(t: ReturnType<typeof trailSummary>)`, `predictionText(list: Prediction[])`, `shareText(share: ReturnType<typeof sportShare>)`, `regularityText(w: WeekStats)`, `lastResultText(acts: StatActivity[], records: PersonalRecord[], p: Period)`

- [ ] **Step 1: Tests**

```ts
expect(split([60, 20, 10, 5, 5])).toEqual({ easy: 0.8, moderate: 0.1, hard: 0.1 });
expect(split([0, 0, 0, 0, 0])).toBeNull();
expect(hrAtPaceText({ paceSKm: 330, from: 158, to: 149, count: 9 })).toBe("Autour de 5:30 /km, ta FC moyenne est passée de 158 à 149 bpm.");
expect(hrAtPaceText({ paceSKm: 330, from: 150, to: 149, count: 9 })).toBe("Autour de 5:30 /km, ta FC moyenne est stable (149 bpm).");
expect(efficiencyText(3)).toBe("Ton efficacité monte de 3 % : tu cours plus vite pour un même cardio.");
expect(efficiencyText(-3)).toBe("Ton efficacité baisse de 3 % sur la période.");
expect(efficiencyText(0.4)).toBe("Ton efficacité est stable sur la période."); // |x| < 1
const f = (ctl: number, atl: number) => ({ date: "2026-11-25", ctl, atl, tsb: ctl - atl });
expect(fitnessText(f(100, 89))).toBe("Tu es frais.");
expect(fitnessText(f(100, 90))).toBe("Ta charge est équilibrée."); // bornes 0,1 et -0,3 incluses
expect(fitnessText(f(100, 130))).toBe("Ta charge est équilibrée.");
expect(fitnessText(f(100, 131))).toBe("Ta fatigue est élevée.");
expect(fitnessText(undefined)).toBeNull();
expect(fitnessText(f(0, 0))).toBeNull();
expect(acwrText(1.3)).toBe("Dans le repère 0,8-1,3 (un repère, pas une prédiction de blessure).");
expect(acwrText(1.31)).toBe("Au-dessus du repère 0,8-1,3 (un repère, pas une prédiction de blessure).");
expect(acwrText(0.79)).toBe("Sous le repère 0,8-1,3 (un repère, pas une prédiction de blessure).");
expect(rampText(0.15)).toBe("Ta dernière semaine complète : +15 % par rapport à la moyenne des 4 précédentes.");
expect(rampText(0.2)).toContain("au-delà du repère de +15 %");
expect(splitText({ easy: 0.75, moderate: 0.25, hard: 0 })).toBe("Proche du 80/20.");
expect(splitText({ easy: 0.7, moderate: 0.21, hard: 0.09 })).toBe("Beaucoup de zone grise.");
expect(splitText({ easy: 0.7, moderate: 0.2, hard: 0.1 })).toBe("Part d'intensité élevée.");
```

`monthlySplit` : mois vide et mois couvert à moins de 50 % présents avec `split: null`. Les autres phrases : un test chacune, valeur donnée contenue dans la phrase, `null` sans donnée. `lastResultText` : le plus récent entre compétition et record datés dans `p`.

- [ ] **Step 2:** `npx vitest run src/lib/stats/intensity.test.ts src/lib/stats/insights.test.ts` → FAIL
- [ ] **Step 3: Implémenter** les signatures ci-dessus.
- [ ] **Step 4:** même commande → PASS
- [ ] **Step 5: Commit** `feat(web): répartition d'intensité et phrases d'interprétation`

### Task 4: Adresses et onglets

**Files:** Create `web/src/lib/stats/tabs.ts`, `tabs.test.ts`, `web/src/components/stats/StatsTabs.svelte` ; Modify `web/src/App.svelte` (`parse`, `go`, `onhash`, rendu), `web/src/routes/Stats.svelte` ; Test `web/src/App.test.ts`, `web/src/readonly.test.ts`

**Interfaces — Produces:**
- `type StatsTab = "overview" | "progress" | "load" | "intensity" | "races"`
- `TABS: { key: StatsTab; label: string; hash: string }[]` (Aperçu, Progression, Charge, Intensité, Records & courses)
- `parseTab(hash: string): StatsTab`
- `Stats` reçoit `tab?: StatsTab` (défaut `overview`) ; `StatsTabs` reçoit `{ tab: StatsTab }`

- [ ] **Step 1: Tests** : `parseTab` sur `#/stats`, `#/stats/load`, `#/stats/inconnu` (→ `overview`), `#/stats/`. App :
  - `#/stats/load` au démarrage reste `#/stats/load`, lien « Charge » `aria-current="page"`, lien « Statistiques » actif ;
  - passer de `#/stats` à `#/stats/progress` : `statsCalls` inchangé ;
  - mêmes deux premières assertions dans `readonly.test.ts`.
- [ ] **Step 2:** `npx vitest run src/lib/stats/tabs.test.ts src/App.test.ts src/readonly.test.ts` → FAIL
- [ ] **Step 3: Implémenter** : `parse()` ramène `stats/…` à `stats` ; `let statsTab = $state(parseTab(location.hash))` relu dans `onhash` et `go`. Onglets : `<nav aria-label="Sous-pages de statistiques">`, défilement horizontal.
- [ ] **Step 4:** même commande → PASS
- [ ] **Step 5: Commit** `feat(web): adresses et onglets des sous-pages de statistiques`

### Task 5: Vues Aperçu, Progression, Intensité, Records & courses

**Files:** Create `web/src/components/stats/views/{Overview,Progress,Intensity,RacesView}.svelte`, `web/src/components/stats/Insight.svelte` ; Modify `web/src/routes/Stats.svelte`, `web/src/components/stats/Filters.svelte` ; Delete `web/src/components/stats/RunningProgress.svelte` (découpé) ; Test `web/src/routes/Stats.test.ts`

Les blocs Volume et Répartition restent affichés sous l'onglet `load` pendant cette tâche ; la tâche 6 les déplace dans `LoadView`.

**Interfaces — Consumes:** tâches 1 à 4. **Produces:**
- `Insight` : `{ text: string | null }` (rien si null) ; `Filters` gagne `showSport?: boolean` (défaut `true`), qui conditionne le choix du sport
- Dans `Stats`, vues de course alimentées par `filterActivities(all, period, "running")`, sans toucher au `sport` mémorisé
- `Overview` : `{ kpis, days, period, weeks, notes: { tab: StatsTab; text: string }[], onpick }`

- [ ] **Step 1: Tests** : rendre l'onglet voulu dans les tests existants (volume → `load`, course → `progress`, records et courses → `races`). Les tests « hidden when sport is bike » deviennent : avec `bike` mémorisé, `progress` affiche les courses, `queryByLabelText("Sport")` est null, `localStorage` garde `bike`. Nouveaux :
  - Aperçu n'affiche ni « Volume », ni « Records », ni « VO2max » ; au plus 4 constats, chacun un lien vers son onglet ; aucun constat sans données ;
  - Progression affiche « Prédicteur », et « Aucune course ou record de moins d'un an » sans référence ; « Pas assez de sorties à cette allure » sous 9 sorties ; le prédicteur ne change pas avec la période ;
  - Intensité affiche « Facile », « Moyen », « Dur », « zones de la montre » ; sans zones : « Pas assez de données sur cette période » ;
  - bannières d'import, erreur et premier import visibles sur `progress`.
- [ ] **Step 2:** `npx vitest run src/routes/Stats.test.ts` → FAIL
- [ ] **Step 3: Implémenter** les vues. Moyenne VO2max en ligne par-dessus les points ; barre unique et barres mensuelles empilées à 100 % avec légende, repère 80 %.
- [ ] **Step 4:** même commande → PASS
- [ ] **Step 5: Commit** `feat(web): vues Aperçu, Progression, Intensité et Records & courses`

### Task 6: Vue Charge

**Files:** Create `web/src/components/stats/views/LoadView.svelte` ; Modify `web/src/routes/Stats.svelte` ; Test `web/src/routes/Stats.test.ts`

**Interfaces — Consumes:** tâche 1, `currentZones()`. `LoadView` : `{ all, sport, current, previous, period, today, zones, metric, onmetric, onpick }` ; `weeklyRamp` reçoit tout l'historique filtré par `sport`.

- [ ] **Step 1: Tests** (mock de `currentZones`) :
  - zones null → « Synchronise Garmin pour calculer ta charge » et volume toujours affiché ;
  - zones valides → groupes « Forme », « Fatigue », « Fraîcheur », « ACWR » ; valeurs identiques après changement de sport puis de période ;
  - textes « Le sport filtre le volume, pas la forme » et « FC repos et max actuelles » ;
  - 3 séances récentes sans FC → « 3 séances sans FC » ; au-delà de 30 % de la durée, avertissement ;
  - moins de 42 jours d'historique → pas de courbe, « Pas assez d'historique ».
- [ ] **Step 2:** `npx vitest run src/routes/Stats.test.ts` → FAIL
- [ ] **Step 3: Implémenter** : volume et répartition repris ; une courbe ECharts à trois séries nommées, distinguées aussi par le trait.
- [ ] **Step 4:** même commande → PASS
- [ ] **Step 5: Commit** `feat(web): vue Charge`

### Task 7: Guide et vérification

**Files:** Modify `README.md` (paragraphe Stats), `docs/guide/index.html` (section `#stats`), `docs/guide/shots.mjs`, `ROADMAP.md`

- [ ] **Step 1:** `shots.mjs` : `stats-run` → `#/stats/progress`, `stats-records` → `#/stats/races`, retirer les défilements devenus inutiles ; textes du guide et du README alignés sur les cinq sous-pages.
- [ ] **Step 2:** régénérer les captures avec une base de démonstration si elle est disponible ; sinon le signaler, ne rien inventer.
- [ ] **Step 3:** depuis `web/` : `npm test`, `npm run build`, `npm run build:mobile` → tout passe.
- [ ] **Step 4:** contrôle visuel des cinq sous-pages, 1280 px et 375 px, clair et sombre : aucun débordement, aucune erreur console.
- [ ] **Step 5: Commit** `docs: sous-pages de statistiques`
