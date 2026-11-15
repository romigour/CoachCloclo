# Consommation Claude dans les Paramètres — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enregistrer le coût de chaque génération de plan et de chaque ajustement Claude, et l'afficher en euros dans une carte « Consommation Claude » de la page Paramètres.

**Architecture:** Les fournisseurs LLM exposent l'usage du dernier appel (`last_usage`) ; `ask_structured` le cumule dans un `UsageMeter` passé en option ; un gestionnaire de contexte de service écrit une ligne `LlmUsage` par action (réussie ou en échec). Une route `GET /api/llm-usage` renvoie un résumé déjà converti en euros ; un composant Svelte l'affiche sous « Mode Claude ».

**Tech Stack:** Python 3 / SQLModel / FastAPI / pytest ; Svelte 5 / TypeScript / vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-11-15-claude-usage-stats-design.md`

## Global Constraints

- Coût stocké en dollars (`cost_usd`), converti à l'affichage avec un taux fixe `USD_TO_EUR = 0.92` (une seule constante, côté backend).
- Montants affichés précédés de « ≈ », format français (`≈ 0,38 €`, deux décimales).
- Une action = une ligne, même après 2 essais ; `attempts` = nombre d'appels Claude ayant renvoyé une réponse.
- `kind` ∈ `generation` | `adjustment` ; `status` ∈ `ok` | `failed` ; `mode` ∈ `cli` | `api`.
- Note obligatoire sous la carte : « Estimation équivalent API, convertie à ≈ 0,92 €/$. En abonnement, ce n'est pas ce que tu paies. »
- `SCHEMA_VERSION` passe de 1 à 2 (règle du dépôt : tout changement de schéma l'incrémente) ; la PWA mobile (`KNOWN_SCHEMA`) passe aussi à 2, sinon elle refuserait la base.
- Pas de graphique, pas de filtre, rien sur la version mobile (la route `setup` n'y existe pas).
- Enveloppe `claude -p --output-format json` vérifiée le 2026-11-15 : `total_cost_usd`, `duration_ms`, `usage.{input_tokens, cache_creation_input_tokens, cache_read_input_tokens, output_tokens}`, `modelUsage` (dict dont la clé est l'id du modèle).

## Review Focus

1. **Échec de génération** (réponse invalide 2 fois, `LLMUsageLimit` renvoyé dans l'enveloppe) : une ligne `failed` est quand même écrite avec le coût consommé, et l'erreur d'origine remonte inchangée à l'utilisateur. → test dans la tâche 3.
2. **Aucun appel abouti** (CLI introuvable, timeout) : aucune ligne n'est écrite (rien de mesurable n'a été consommé). → test dans la tâche 3.
3. **Modèle inconnu de la table de tarifs en mode API** (ex. modèle saisi à la main) : `cost_usd = None`, la ligne est écrite, l'affichage montre « — » et le total ignore la ligne au lieu de planter. → tests tâches 1 et 3.
4. **Dates stockées sans fuseau par SQLite** : la route renvoie des ISO avec `+00:00`, sinon le front décale l'heure d'une heure. → test tâche 4.
5. **Base vide / première ouverture** : la carte affiche « Aucune génération enregistrée pour l'instant » et ne plante pas sur la moyenne `null`. → test tâche 5.

---

### Task 1: Capture de l'usage par les fournisseurs

**Files:**
- Create: `coach/llm/usage.py`
- Modify: `coach/llm/provider.py` (`ClaudeCliProvider.complete`, `AnthropicApiProvider.complete`, `FakeLLMProvider`)
- Test: `tests/llm/test_usage.py`, `tests/llm/test_provider.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class CallUsage: mode: str; model: str | None; input_tokens: int; output_tokens: int; cost_usd: float | None; duration_ms: int`
  - `PRICES_PER_MTOK: dict[str, tuple[float, float, float, float]]` (entrée, sortie, écriture cache, lecture cache)
  - `api_cost_usd(model: str, input_tokens: int, output_tokens: int, cache_write: int = 0, cache_read: int = 0) -> float | None`
  - `USD_TO_EUR = 0.92` et `to_eur(usd: float | None) -> float | None` (arrondi à 4 décimales)
  - Attribut `last_usage: CallUsage | None` sur les trois fournisseurs, remis à `None` au début de chaque `complete`, renseigné dès qu'une réponse de Claude a été lue (y compris si `complete` lève ensuite `LLMUsageLimit`/`LLMError` sur une enveloppe `is_error`).
  - `FakeLLMProvider(responses, usage: CallUsage | None = None)` : met `last_usage = usage` à chaque appel.

Tarifs (API Anthropic, $/MTok, relevés le 2026-11-15) ; écriture cache = 1,25 × entrée :

| modèle | entrée | sortie | écriture cache | lecture cache |
|---|---|---|---|---|
| `claude-fable-5-2` | 8.00 | 40.00 | 10.00 | 0.20 |
| `claude-opus-5-5` | 4.00 | 20.00 | 5.00 | 0.20 |
| `claude-sonnet-5-5` | 2.00 | 10.00 | 2.50 | 0.10 |
| `claude-haiku-5-5` | 0.10 | 0.50 | 0.125 | 0.01 |

`input_tokens` de `CallUsage` = taille totale du prompt (`input_tokens + cache_creation_input_tokens + cache_read_input_tokens`).

- [ ] **Step 1: Tests de `coach/llm/usage.py`** dans `tests/llm/test_usage.py`

```python
def test_api_cost_sonnet():
    assert api_cost_usd("claude-sonnet-5-5", 1_000_000, 100_000) == pytest.approx(3.0)

def test_api_cost_with_cache():
    assert api_cost_usd("claude-opus-5-5", 0, 0, cache_write=1_000_000, cache_read=1_000_000) == pytest.approx(5.2)

def test_api_cost_unknown_model_is_none():
    assert api_cost_usd("modele-perso", 1000, 1000) is None

def test_to_eur():
    assert to_eur(1.0) == pytest.approx(0.92)
    assert to_eur(None) is None
```

- [ ] **Step 2: Tests fournisseurs** dans `tests/llm/test_provider.py` (réutiliser `fake_run`, `which_ok`)

```python
ENVELOPE = {"type": "result", "is_error": False, "result": "{}", "duration_ms": 3132,
            "total_cost_usd": 0.0102,
            "usage": {"input_tokens": 2, "cache_creation_input_tokens": 4864,
                      "cache_read_input_tokens": 649, "output_tokens": 77},
            "modelUsage": {"claude-sonnet-5-5": {}}}

def test_cli_records_usage():
    p = ClaudeCliProvider(runner=fake_run(json.dumps(ENVELOPE)), which=which_ok, cwd=tmp)
    p.complete("s", "p")
    assert p.last_usage == CallUsage(mode="cli", model="claude-sonnet-5-5", input_tokens=5515,
                                     output_tokens=77, cost_usd=0.0102, duration_ms=3132)

def test_cli_usage_kept_when_envelope_is_error():
    env = {**ENVELOPE, "is_error": True, "result": "usage limit reached"}
    ...  # pytest.raises(LLMUsageLimit) ; p.last_usage.cost_usd == 0.0102

def test_cli_usage_reset_when_cli_missing():
    ...  # après un appel réussi, puis which renvoyant None → LLMUnavailable et p.last_usage is None

def test_api_records_usage():
    # client factice : messages.create renvoie SimpleNamespace(content=[text], usage=SimpleNamespace(
    #   input_tokens=1000, output_tokens=500, cache_creation_input_tokens=None, cache_read_input_tokens=None))
    # → last_usage.mode == "api", model == "claude-sonnet-5-5", input_tokens == 1000,
    #   cost_usd == approx(0.007), duration_ms >= 0
```

- [ ] **Step 3: Lancer les tests, vérifier l'échec**

Run: `uv run pytest tests/llm/test_usage.py tests/llm/test_provider.py -q`
Expected: FAIL (`ModuleNotFoundError: coach.llm.usage`)

- [ ] **Step 4: Implémenter `coach/llm/usage.py` et `last_usage` dans `provider.py`**

CLI : champs manquants → 0 ; `model` = première clé de `modelUsage` ou `None` ; `cost_usd = envelope.get("total_cost_usd")`. API : durée mesurée avec `time.monotonic()` autour de `messages.create` ; champs de cache `None` → 0 ; coût via `api_cost_usd(self.model, …)`.

- [ ] **Step 5: Lancer les tests, vérifier le succès**

Run: `uv run pytest tests/llm -q`
Expected: PASS (dont les tests existants)

- [ ] **Step 6: Commit**

```bash
git add coach/llm/usage.py coach/llm/provider.py tests/llm/test_usage.py tests/llm/test_provider.py
git commit -m "feat(llm): les fournisseurs remontent tokens, durée et coût du dernier appel"
```

---

### Task 2: Cumul des essais dans `ask_structured`

**Files:**
- Modify: `coach/llm/usage.py` (ajout `UsageMeter`), `coach/llm/client.py`
- Test: `tests/llm/test_client.py`

**Interfaces:**
- Consumes: `CallUsage`, `last_usage` (tâche 1).
- Produces:
  - `class UsageMeter` avec `add(u: CallUsage | None) -> None` (ignore `None`), propriétés `attempts: int`, `input_tokens: int`, `output_tokens: int`, `duration_ms: int`, `cost_usd: float | None` (somme ; `None` si un essai a un coût `None`), `mode: str | None`, `model: str | None` (ceux du dernier essai).
  - `ask_structured(provider, system, prompt, model, validate=..., meter: UsageMeter | None = None) -> T` : après chaque appel à `provider.complete` (qu'il rende ou lève), `meter.add(getattr(provider, "last_usage", None))`.

- [ ] **Step 1: Tests** dans `tests/llm/test_client.py`

```python
U = CallUsage(mode="cli", model="m", input_tokens=100, output_tokens=10, cost_usd=0.5, duration_ms=1000)

def test_meter_sums_two_attempts():
    llm = FakeLLMProvider(["pas du json", VALID_JSON], usage=U)
    meter = UsageMeter()
    ask_structured(llm, "s", "p", SomeModel, meter=meter)
    assert (meter.attempts, meter.input_tokens, meter.cost_usd, meter.duration_ms) == (2, 200, 1.0, 2000)

def test_meter_filled_on_final_failure():
    # deux réponses invalides → LLMInvalidResponse ; meter.attempts == 2

def test_meter_counts_call_that_raised():
    # fournisseur dont complete() pose last_usage = U puis lève LLMUsageLimit
    # → pytest.raises(LLMUsageLimit) et meter.attempts == 1

def test_meter_cost_none_if_one_attempt_unknown():
    # deux usages, dont un avec cost_usd=None → meter.cost_usd is None
```

(Reprendre le modèle pydantic et le JSON valide déjà utilisés dans `test_client.py`.)

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `uv run pytest tests/llm/test_client.py -q`
Expected: FAIL (`ImportError: UsageMeter`)

- [ ] **Step 3: Implémenter `UsageMeter` et le paramètre `meter`** (un `try/finally` autour de chaque `provider.complete`).

- [ ] **Step 4: Lancer, vérifier le succès**

Run: `uv run pytest tests/llm -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add coach/llm/usage.py coach/llm/client.py tests/llm/test_client.py
git commit -m "feat(llm): ask_structured cumule l'usage des essais"
```

---

### Task 3: Table `LlmUsage`, enregistrement et résumé

**Files:**
- Modify: `coach/plan/models.py` (table), `coach/plan/repo.py` (`SCHEMA_VERSION = 2`, méthode `llm_usages`), `web/src/lib/turso/db.ts` (`KNOWN_SCHEMA = 2`), `web/src/lib/turso/db.test.ts` (le cas « trop récent » passe de `{"v":2}` à `{"v":3}`)
- Create: `coach/services/llm_usage.py`
- Modify: `coach/services/plans.py` (`generate_plan`), `coach/services/adjust.py` (`ask_adjustment`)
- Test: `tests/services/test_llm_usage.py`

**Interfaces:**
- Consumes: `UsageMeter`, `ask_structured(..., meter=)`, `to_eur` (tâches 1-2).
- Produces:
  - `class LlmUsage(SQLModel, table=True)` : `id: int | None` (PK), `created_at: dt.datetime = Field(default_factory=_now)`, `kind: str`, `mode: str | None`, `model: str | None`, `attempts: int`, `input_tokens: int`, `output_tokens: int`, `cost_usd: float | None`, `duration_ms: int`, `status: str`.
  - `Repo.llm_usages() -> list[LlmUsage]` (du plus récent au plus ancien).
  - `@contextmanager tracked(repo: Repo, kind: str) -> Iterator[UsageMeter]` : à la sortie, si `meter.attempts > 0`, ajoute une ligne avec `status="ok"` (sortie normale) ou `"failed"` (exception, qui est relancée telle quelle).
  - `usage_summary(repo: Repo, now: dt.datetime) -> dict` :
    ```
    {"month": {"generations": int, "adjustments": int, "cost_eur": float},
     "avg_generation_eur": float | None,
     "recent": [ {"created_at": str ISO avec fuseau, "kind", "status", "attempts",
                  "cost_eur": float | None, "input_tokens", "output_tokens", "duration_ms",
                  "mode", "model"} ]   # 10 plus récentes
    }
    ```
    Mois = mois calendaire de `now` en heure locale (`created_at` relu sans fuseau = UTC). `month.cost_eur` = somme des coûts connus (toutes lignes du mois, échecs compris). `avg_generation_eur` = moyenne des générations `ok` à coût connu, toutes dates ; `None` s'il n'y en a pas.
  - `generate_plan` : `with tracked(repo, "generation") as meter:` autour de `ask_structured(..., meter=meter)`. `ask_adjustment` : idem avec `"adjustment"` (couvre ses 4 appelants).

- [ ] **Step 1: Tests** dans `tests/services/test_llm_usage.py` (fixture `repo`)

```python
def test_tracked_writes_ok_row(repo):
    with tracked(repo, "generation") as m:
        m.add(U)
    [row] = repo.llm_usages()
    assert (row.kind, row.status, row.attempts, row.cost_usd) == ("generation", "ok", 1, 0.5)

def test_tracked_writes_failed_row_and_reraises(repo):
    with pytest.raises(LLMInvalidResponse):
        with tracked(repo, "generation") as m:
            m.add(U); m.add(U)
            raise LLMInvalidResponse(["x"])
    [row] = repo.llm_usages()
    assert (row.status, row.attempts, row.cost_usd) == ("failed", 2, 1.0)

def test_tracked_no_row_without_attempt(repo):
    with pytest.raises(LLMUnavailable):
        with tracked(repo, "generation"):
            raise LLMUnavailable("CLI claude introuvable")
    assert repo.llm_usages() == []

def test_summary_month_and_average(repo):
    # lignes : 2 générations ok ce mois (0.40 $, 0.60 $), 1 génération failed ce mois (0.20 $),
    #          1 ajustement ce mois (0.10 $), 1 génération ok le mois précédent (1.00 $),
    #          1 génération ok à coût None ce mois
    s = usage_summary(repo, now)
    assert s["month"] == {"generations": 4, "adjustments": 1, "cost_eur": approx(1.30 * 0.92)}
    assert s["avg_generation_eur"] == approx((0.40 + 0.60 + 1.00) / 3 * 0.92)
    assert len(s["recent"]) == 6 and s["recent"][0]["created_at"].endswith("+00:00")

def test_summary_empty(repo):
    assert usage_summary(repo, now) == {"month": {"generations": 0, "adjustments": 0, "cost_eur": 0.0},
                                        "avg_generation_eur": None, "recent": []}

def test_summary_keeps_ten_most_recent(repo): ...

def test_generate_plan_records_usage(repo, ...):
    # même mise en place que le test nominal de tests/services/test_plans.py,
    # avec FakeLLMProvider(..., usage=U) → une ligne kind="generation", status="ok"

def test_adjustment_records_usage(repo, ...):
    # même mise en place qu'un test nominal de tests/services/test_adjust.py → kind="adjustment"
```

Les lignes de `test_summary_*` sont insérées directement via `repo.add(LlmUsage(...))` avec un `created_at` choisi.

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `uv run pytest tests/services/test_llm_usage.py -q`
Expected: FAIL (`ImportError`)

- [ ] **Step 3: Implémenter la table, `SCHEMA_VERSION = 2`, `Repo.llm_usages`, `coach/services/llm_usage.py`, et le branchement dans `generate_plan` / `ask_adjustment`**

- [ ] **Step 4: Monter `KNOWN_SCHEMA` à 2 dans `web/src/lib/turso/db.ts` et passer le test « trop récent » de `db.test.ts` à `{"v":3}`**

- [ ] **Step 5: Lancer toute la suite**

Run: `uv run pytest -q` puis `cd web && npx vitest run src/lib/turso`
Expected: PASS (les tests existants de schéma, s'ils vérifient `SCHEMA_VERSION == 1`, sont mis à jour vers 2)

- [ ] **Step 6: Commit**

```bash
git add coach/plan/models.py coach/plan/repo.py coach/services/llm_usage.py coach/services/plans.py coach/services/adjust.py tests/services/test_llm_usage.py web/src/lib/turso/db.ts web/src/lib/turso/db.test.ts
git commit -m "feat: enregistre la consommation Claude de chaque génération et ajustement"
```

---

### Task 4: Route `GET /api/llm-usage`

**Files:**
- Modify: `coach/api/app.py` (section « réglages », après `put_settings`)
- Test: `tests/api/test_app.py`

**Interfaces:**
- Consumes: `usage_summary(repo, now)` (tâche 3).
- Produces: `GET /api/llm-usage` → JSON de `usage_summary(repo, dt.datetime.now(dt.timezone.utc))`. Route avec `RepoDep` (nécessite la base : ne pas l'ajouter à `NO_DB_PATHS`).

- [ ] **Step 1: Tests** dans `tests/api/test_app.py` (fixtures `make_client`, `repo`)

```python
def test_llm_usage_empty(make_client):
    assert make_client().get("/api/llm-usage").json()["recent"] == []

def test_llm_usage_lists_rows_with_timezone(make_client, repo):
    repo.add(LlmUsage(kind="generation", mode="cli", model="m", attempts=1, input_tokens=1,
                      output_tokens=1, cost_usd=0.5, duration_ms=1, status="ok"))
    body = make_client().get("/api/llm-usage").json()
    assert body["recent"][0]["cost_eur"] == pytest.approx(0.46)
    assert body["recent"][0]["created_at"].endswith("+00:00")
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `uv run pytest tests/api/test_app.py -k llm_usage -q`
Expected: FAIL (404)

- [ ] **Step 3: Ajouter la route**

- [ ] **Step 4: Lancer, vérifier le succès**

Run: `uv run pytest tests/api -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add coach/api/app.py tests/api/test_app.py
git commit -m "feat(api): route de lecture de la consommation Claude"
```

---

### Task 5: Carte « Consommation Claude » dans Paramètres

**Files:**
- Modify: `web/src/lib/api.ts` (type + méthode)
- Create: `web/src/components/ClaudeUsage.svelte`, `web/src/components/ClaudeUsage.test.ts`
- Modify: `web/src/routes/Setup.svelte` (insérer `<ClaudeUsage />` juste après la section « Mode Claude »)

**Interfaces:**
- Consumes: `GET /api/llm-usage` (tâche 4).
- Produces:
  - `export type LlmUsageRow = { created_at: string; kind: "generation" | "adjustment"; status: "ok" | "failed"; attempts: number; cost_eur: number | null; input_tokens: number; output_tokens: number; duration_ms: number; mode: "cli" | "api" | null; model: string | null }`
  - `export type LlmUsageView = { month: { generations: number; adjustments: number; cost_eur: number }; avg_generation_eur: number | null; recent: LlmUsageRow[] }`
  - `api.llmUsage: () => get<LlmUsageView>("/llm-usage")`

Rendu (copie fixée par la spec) :

```
<h2>Consommation Claude</h2>
Ce mois-ci : {g} générations · {a} ajustements · ≈ {total}
Coût moyen d'une génération de plan : ≈ {moyenne}        (ligne absente si null)
Dernières actions
  {date courte + heure locale}  Génération de plan | Ajustement  ≈ {coût} | —  [2 essais] [échec]
  détail (<details> ou title) : {tokens entrée} / {tokens sortie} tokens · {durée en s} · {modèle}
Estimation équivalent API, convertie à ≈ 0,92 €/$. En abonnement, ce n'est pas ce que tu paies.
```

Liste vide → « Aucune génération enregistrée pour l'instant » à la place des deux premières lignes et de la liste. Échec de chargement → la carte affiche un message court, sans bloquer la page. Format euro : `Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", minimumFractionDigits: 2, maximumFractionDigits: 2 })`.

- [ ] **Step 1: Tests** dans `web/src/components/ClaudeUsage.test.ts` (`vi.mock("../lib/api")`, comme les autres tests de composants)

```ts
test("affiche total du mois, moyenne et dernières actions", async () => {
  // llmUsage → month {generations: 4, adjustments: 3, cost_eur: 2.1}, avg 0.38,
  //   recent: [generation ok attempts 2 cost 0.41, adjustment failed cost null]
  expect(await screen.findByText(/4 générations · 3 ajustements · ≈ 2,10 €/)).toBeInTheDocument();
  expect(screen.getByText(/Coût moyen d'une génération de plan : ≈ 0,38 €/)).toBeInTheDocument();
  expect(screen.getByText("2 essais")).toBeInTheDocument();
  expect(screen.getByText("échec")).toBeInTheDocument();
  expect(screen.getByText("—")).toBeInTheDocument();
  expect(screen.getByText(/En abonnement, ce n'est pas ce que tu paies/)).toBeInTheDocument();
});

test("base vide", async () => {
  // month à 0, avg null, recent []
  expect(await screen.findByText("Aucune génération enregistrée pour l'instant")).toBeInTheDocument();
  expect(screen.queryByText(/Coût moyen/)).toBeNull();
});
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `cd web && npx vitest run src/components/ClaudeUsage.test.ts`
Expected: FAIL (composant introuvable)

- [ ] **Step 3: Implémenter le type, `api.llmUsage`, le composant et l'insertion dans `Setup.svelte`** (classes CSS existantes : `card stack`, `row`, comme `UpdateSettings.svelte`)

- [ ] **Step 4: Lancer toute la suite front et le typage**

Run: `cd web && npm test && npm run build`
Expected: tests PASS, build sans erreur

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/api.ts web/src/components/ClaudeUsage.svelte web/src/components/ClaudeUsage.test.ts web/src/routes/Setup.svelte
git commit -m "feat(web): carte Consommation Claude dans les Paramètres"
```
