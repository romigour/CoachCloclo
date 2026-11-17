# Journaux de diagnostic Claude et Garmin — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deux interrupteurs dans Paramètres qui, activés, consignent chaque appel Claude (prompts et réponses complets) et chaque appel Garmin (méthode, paramètres, réponse) dans `claude.log` et `garmin.log`, secrets masqués.

**Architecture:** Un module `coach/trace.py` porte tout : lecture des réglages à chaque appel (effet immédiat), loggers dédiés non propagés avec rotation, masquage, sérialisation JSON tolérante, et avale toute erreur d'écriture. Les fournisseurs LLM et `GarminClient._call` l'appellent. L'API expose `GET/PUT /api/diagnostics` ; le routeur desktop ajoute l'ouverture du dossier. Une carte Svelte `DiagnosticSettings` dans l'écran Paramètres (`Setup.svelte`).

**Tech Stack:** Python 3 / FastAPI / pydantic / `logging.handlers.RotatingFileHandler` ; Svelte 5 + vitest + @testing-library/svelte.

**Spec:** `docs/superpowers/specs/2026-11-17-debug-traces-design.md`

## Global Constraints

- Les deux interrupteurs sont désactivés par défaut.
- Fichiers : `<data_dir()>/logs/claude.log` et `<data_dir()>/logs/garmin.log`, `RotatingFileHandler(maxBytes=5_000_000, backupCount=3, encoding="utf-8")`.
- Loggers `coach.trace.claude` et `coach.trace.garmin`, `propagate = False` : rien dans `coachcloclo.log`.
- Réponses Garmin tronquées à 20 000 caractères par entrée ; textes Claude jamais tronqués.
- Format d'une entrée : ligne `horodatage NIVEAU [id] événement`, puis le contenu en JSON indenté (2 espaces, `ensure_ascii=False`).
- Jamais dans un journal : mot de passe Garmin, code MFA, tokens Garmin, clé API Anthropic, token Turso.
- Une erreur d'écriture du journal ne fait jamais échouer ni changer le résultat d'un appel.
- Activation/désactivation sans redémarrage.
- Textes de l'interface en français.
- Tests Python : `uv run pytest` ; tests web : `npm --prefix web test`.

## Review Focus

1. **Dossier de journaux inaccessible ou disque plein** → l'appel Claude/Garmin réussit quand même (test : handler dont `emit` lève, `complete` renvoie le texte) — Task 1.
2. **Connexion Garmin** → le mot de passe et le code MFA n'apparaissent jamais dans `garmin.log`, même en cas d'erreur de connexion — Task 3.
3. **Valeurs non sérialisables** (dates, dataclasses, bytes, objets SDK) dans paramètres ou réponses → consignées via `str()`, pas d'exception — Task 1.
4. **Délai dépassé du CLI avec sortie partielle en `bytes` ou `None`** → l'entrée « délai dépassé » est écrite, décodée en texte, et `LLMTimeout` est toujours levée — Task 2.
5. **`COACH_HOME` qui change (tests, bascule)** → le journal suit le dossier courant ; le cache de handlers est indexé par chemin — Task 1.

---

### Task 1: Module `coach/trace.py` et réglages

**Files:**
- Modify: `coach/config.py` (classe `Settings`)
- Create: `coach/trace.py`
- Test: `tests/test_trace.py`

**Interfaces:**
- Produces:
  - `Settings.trace_claude: bool = False`, `Settings.trace_garmin: bool = False`
  - `Category = Literal["claude", "garmin"]`
  - `logs_dir() -> Path` : `data_dir() / "logs"` (créé à la demande)
  - `enabled(category: Category) -> bool` : lit `load_settings()` à chaque appel ; toute exception → `False`
  - `new_call_id() -> str` : 8 caractères hexadécimaux
  - `record(category: Category, call_id: str, event: str, *, level: int = logging.INFO, **fields: Any) -> None` : n'écrit que si `enabled(category)` ; masque ; avale toute exception
  - `redact(value: Any, secrets: Iterable[str] = ()) -> Any` : copie masquée
  - `GARMIN_MAX_CHARS = 20_000` et `truncate(text: str, limit: int) -> str`
  - `_reset_handlers() -> None` (tests) : ferme et oublie les handlers en cache

- [ ] **Step 1: Write the failing tests** (`tests/test_trace.py`, fixture `coach_home` de `tests/conftest.py`)

```python
def read(cat): return (logs_dir() / f"{cat}.log").read_text(encoding="utf-8")

def test_disabled_by_default_writes_nothing(coach_home):
    record("claude", "abc", "requête", prompt="x")
    assert not (logs_dir() / "claude.log").exists()

def test_enabled_writes_header_and_json(coach_home):
    save_settings(Settings(trace_claude=True))
    record("claude", "abc12345", "requête", prompt="Bonjour é")
    text = read("claude")
    assert "[abc12345] requête" in text
    assert '"prompt": "Bonjour é"' in text
    assert not (logs_dir() / "garmin.log").exists()

def test_toggle_takes_effect_without_restart(coach_home):
    save_settings(Settings(trace_garmin=True)); record("garmin", "1", "a")
    save_settings(Settings(trace_garmin=False)); record("garmin", "2", "b")
    assert "[1] a" in read("garmin") and "[2] b" not in read("garmin")

def test_redact_keys_and_literal_secrets():
    out = redact({"password": "p", "nested": [{"oauth2_token": "t", "ok": 1}],
                  "Authorization": "Bearer z", "text": "clé sk-ant-123 ici"}, ["sk-ant-123"])
    assert out == {"password": "***", "nested": [{"oauth2_token": "***", "ok": 1}],
                   "Authorization": "***", "text": "clé *** ici"}

def test_record_masks_settings_secrets(coach_home):
    save_settings(Settings(trace_claude=True, anthropic_api_key="sk-ant-SECRET", turso_token="tt-SECRET"))
    record("claude", "1", "requête", prompt="sk-ant-SECRET et tt-SECRET")
    assert "SECRET" not in read("claude")

def test_unserializable_values_are_stringified(coach_home):
    save_settings(Settings(trace_garmin=True))
    record("garmin", "1", "appel", d=date(2026, 11, 17), b=b"\xff", o=object())
    assert '"2026-11-17"' in read("garmin")

def test_write_failure_is_swallowed(coach_home, monkeypatch):
    save_settings(Settings(trace_claude=True))
    monkeypatch.setattr(RotatingFileHandler, "emit", lambda *a: (_ for _ in ()).throw(OSError("disque plein")))
    record("claude", "1", "requête")  # ne lève pas

def test_follows_coach_home_change(tmp_path, monkeypatch):
    for name in ("a", "b"):
        monkeypatch.setenv("COACH_HOME", str(tmp_path / name))
        save_settings(Settings(trace_claude=True)); record("claude", name, "e")
    assert "[b] e" in (tmp_path / "b" / "logs" / "claude.log").read_text(encoding="utf-8")
    assert "[b] e" not in (tmp_path / "a" / "logs" / "claude.log").read_text(encoding="utf-8")

def test_truncate():
    assert truncate("abcdef", 3) == "abc… [tronqué, 6 caractères au total]"
    assert truncate("abc", 3) == "abc"
```

Ajouter une fixture autouse dans ce fichier qui appelle `_reset_handlers()` après chaque test (Windows ne libère pas un fichier ouvert).

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_trace.py -v`
Expected: FAIL (ImportError `coach.trace`)

- [ ] **Step 3: Implement**

`Settings` : deux champs booléens après `turso_token`. `coach/trace.py` : clés masquées si le nom en minuscules contient l'un de `password`, `passwd`, `token`, `secret`, `api_key`, `apikey`, `authorization`, `cookie`, `oauth`, `ticket`, `mfa` ; secrets littéraux = `anthropic_api_key` et `turso_token` des réglages (non vides). Sérialisation : `json.dumps(redact(fields, secrets), indent=2, ensure_ascii=False, default=str)`. Handlers en cache `dict[Path, RotatingFileHandler]` ; le logger de la catégorie retire l'ancien handler quand le chemin change. Formatter `"%(asctime)s %(levelname)s %(message)s"`, message `f"[{call_id}] {event}\n{json}"`. Tout le corps de `record` (lecture des réglages, masquage, sérialisation, écriture) dans `try/except Exception: pass` : le test remplace `emit` par une fonction qui lève, l'exception remonte par `logger.log` et doit être avalée là.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_trace.py tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add coach/config.py coach/trace.py tests/test_trace.py
git commit -m "feat: module de journaux de diagnostic"
```

---

### Task 2: Journal des appels Claude

**Files:**
- Modify: `coach/llm/provider.py` (`ClaudeCliProvider.complete`, `AnthropicApiProvider.complete`)
- Test: `tests/llm/test_provider.py`

**Interfaces:**
- Consumes: `trace.record`, `trace.new_call_id`, `trace.enabled` (Task 1)
- Produces: événements `claude.log` : `requête`, `sortie` (CLI), `réponse`, `délai dépassé`, `erreur`

Comportement : un `call_id` par appel de `complete`. `requête` écrite **avant** l'appel avec `mode` (`"cli"`/`"api"`), `model` (API) ou `args` (CLI, l'élément après `--system-prompt` remplacé par `"<prompt système ci-dessous>"`), `timeout_s` (CLI), `system`, `prompt`. CLI : `sortie` juste après le retour du runner avec `returncode`, `stdout`, `stderr`, `duration_ms`. `réponse` avec `text` et `usage` (`dataclasses.asdict(self.last_usage)`). `délai dépassé` (niveau WARNING) avec `duration_ms`, `stdout`, `stderr` partiels de `TimeoutExpired` (bytes décodés UTF-8 avec `errors="replace"`, `None` → `""`). Toute autre `LLMError` ou exception : `erreur` (niveau ERROR) avec `type` et `message`, puis on relève l'exception d'origine. Mettre le corps actuel dans une méthode privée `_run(system, prompt, call_id)` et l'envelopper dans `complete` pour ne pas dupliquer la gestion d'erreur.

- [ ] **Step 1: Write the failing tests** (réutiliser `fake_run` existant)

```python
def claude_log(coach_home): return (coach_home / "logs" / "claude.log").read_text(encoding="utf-8")

def test_cli_traces_request_output_and_response(coach_home):
    save_settings(Settings(trace_claude=True))
    env = {"result": "ok", "usage": {"input_tokens": 1, "output_tokens": 2}, "duration_ms": 5}
    ClaudeCliProvider(runner=fake_run(stdout=json.dumps(env))).complete("SYS-PROMPT", "USER-PROMPT")
    log = claude_log(coach_home)
    assert log.index("requête") < log.index("sortie") < log.index("réponse")
    assert "SYS-PROMPT" in log and "USER-PROMPT" in log and '"text": "ok"' in log
    assert len(set(re.findall(r"\[([0-9a-f]{8})\]", log))) == 1

def test_cli_timeout_traces_partial_output(coach_home):
    save_settings(Settings(trace_claude=True))
    exc = subprocess.TimeoutExpired(["claude"], 180, output=b"partiel", stderr=None)
    with pytest.raises(LLMTimeout):
        ClaudeCliProvider(runner=fake_run(raises=exc)).complete("s", "p")
    log = claude_log(coach_home)
    assert "requête" in log and "délai dépassé" in log and "partiel" in log

def test_cli_error_traced_and_reraised(coach_home):
    save_settings(Settings(trace_claude=True))
    with pytest.raises(LLMError):
        ClaudeCliProvider(runner=fake_run(stdout="pas du json", returncode=1)).complete("s", "p")
    assert "erreur" in claude_log(coach_home)

def test_api_traces_request_and_response_without_key(coach_home):
    save_settings(Settings(trace_claude=True, anthropic_api_key="sk-ant-SECRET"))
    # client factice existant du fichier, réponse texte "ok"
    AnthropicApiProvider("sk-ant-SECRET", "m1", client=<client factice>).complete("SYS", "USR")
    log = claude_log(coach_home)
    assert '"model": "m1"' in log and '"text": "ok"' in log and "SECRET" not in log

def test_no_trace_when_disabled(coach_home):
    env = {"result": "ok"}
    ClaudeCliProvider(runner=fake_run(stdout=json.dumps(env))).complete("s", "p")
    assert not (coach_home / "logs" / "claude.log").exists()
```

Vérifier comment `fake_run(raises=...)` et le client API factice sont construits dans le fichier et s'y conformer. Ajouter la fixture `_reset_handlers` autouse comme en Task 1.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/llm/test_provider.py -v`
Expected: les nouveaux tests FAIL, les anciens PASS

- [ ] **Step 3: Implement** selon le comportement ci-dessus.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/llm -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add coach/llm/provider.py tests/llm/test_provider.py
git commit -m "feat(llm): journal de diagnostic des appels Claude"
```

---

### Task 3: Journal des appels Garmin

**Files:**
- Modify: `coach/garmin/client.py` (`_call`, `from_tokens`, `start_login`, `finish_login`)
- Test: `tests/garmin/test_client.py`

**Interfaces:**
- Consumes: `trace.record`, `trace.new_call_id`, `trace.truncate`, `trace.GARMIN_MAX_CHARS` (Task 1)
- Produces: événements `garmin.log` : `appel`, `réponse`, `limite atteinte, nouvelle tentative`, `erreur`, `connexion`

Comportement de `_call` : un `call_id` par appel. `appel` avec `method` (`getattr(fn, "__name__", repr(fn))`), `args`, `kwargs`. `réponse` avec `duration_ms`, `size` (longueur du JSON) et `body` = `truncate(json.dumps(result, default=str, ensure_ascii=False), GARMIN_MAX_CHARS)`. Sur 429 à la première tentative : `limite atteinte, nouvelle tentative` (WARNING). Sur exception finale : `erreur` (ERROR) avec `type` (classe garminconnect) et `message`. Ne pas sérialiser la réponse si le journal est désactivé (`trace.enabled("garmin")` testé une fois au début de `_call`) pour ne rien coûter.

Connexion : `connexion` avec `step` (`"tokens"`, `"identifiants"`, `"mfa"`) et `outcome` (`"ok"`, `"needs_mfa"` ou nom de l'exception levée). Jamais l'email, le mot de passe, le code, le `state` MFA ni le chemin du tokenstore.

- [ ] **Step 1: Write the failing tests** (avec `FakeLib` existant)

```python
def garmin_log(coach_home): return (coach_home / "logs" / "garmin.log").read_text(encoding="utf-8")

def test_call_traces_method_params_and_response(coach_home):
    save_settings(Settings(trace_garmin=True))
    lib = FakeLib(responses={"get_activities": load("activities")})
    GarminClient(lib).activities_page(0, 20)
    log = garmin_log(coach_home)
    assert '"method": "get_activities"' in log and "20" in log and "réponse" in log

def test_long_response_truncated(coach_home):
    save_settings(Settings(trace_garmin=True))
    lib = FakeLib(responses={"get_activities": [{"x": "a" * 30_000}]})
    GarminClient(lib).activities_page(0, 1)
    assert "tronqué" in garmin_log(coach_home)

def test_rate_limit_retry_and_error_traced(coach_home):
    save_settings(Settings(trace_garmin=True))
    lib = FakeLib(error=GarminConnectTooManyRequestsError("429"))
    with pytest.raises(GarminRateLimited):
        GarminClient(lib, sleep=lambda s: None).activities_page(0, 1)
    log = garmin_log(coach_home)
    assert "nouvelle tentative" in log and "erreur" in log

def test_login_never_logs_credentials(coach_home, monkeypatch):
    save_settings(Settings(trace_garmin=True))
    # Garmin factice dont login() lève GarminConnectAuthenticationError
    with pytest.raises(GarminAuthRequired):
        GarminClient.start_login("moi@exemple.fr", "MotDePasse!", coach_home / "tok")
    log = garmin_log(coach_home)
    assert "connexion" in log and "MotDePasse!" not in log and "moi@exemple.fr" not in log
```

Adapter `FakeLib` à la façon dont il expose les méthodes (vérifier sa définition) ; pour la connexion, monkeypatcher `coach.garmin.client.Garmin`. Fixture `_reset_handlers` autouse.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/garmin/test_client.py -v`
Expected: nouveaux tests FAIL

- [ ] **Step 3: Implement** selon le comportement ci-dessus.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/garmin -v`
Expected: PASS (le test live reste ignoré comme avant)

- [ ] **Step 5: Commit**

```bash
git add coach/garmin/client.py tests/garmin/test_client.py
git commit -m "feat(garmin): journal de diagnostic des appels Garmin"
```

---

### Task 4: Routes API de diagnostic

**Files:**
- Modify: `coach/api/app.py` (section réglages, `SettingsBody` voisin)
- Modify: `coach/api/desktop_routes.py`
- Modify: `coach/desktop/context.py` (`Desktop`, nouvelle fonction `open_folder`)
- Modify: `coach/desktop/launcher.py` (rien si le champ a une valeur par défaut — vérifier)
- Test: `tests/api/test_app.py`, `tests/api/test_desktop_routes.py`

**Interfaces:**
- Consumes: `Settings.trace_claude/trace_garmin`, `trace.logs_dir()` (Task 1)
- Produces:
  - `GET /api/diagnostics` → `{"trace_claude": bool, "trace_garmin": bool, "logs_dir": str, "can_open": bool}` ; `can_open = desktop is not None and is_loopback(request)`
  - `PUT /api/diagnostics` corps `DiagnosticsBody {trace_claude: bool | None = None, trace_garmin: bool | None = None}` → même vue ; ne modifie que les champs fournis (relire `load_settings()` juste avant `save_settings`)
  - `POST /api/logs/open` (routeur desktop) : 403 `local_only` hors boucle locale, sinon `desktop.open_folder(logs_dir())` → `{"status": "ok"}`
  - `Desktop.open_folder: Callable[[Path], None] = open_folder` ; `open_folder(path)` : `os.startfile` sous Windows, sinon `subprocess.Popen(["open" si darwin sinon "xdg-open", str(path)])`

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_app.py
def test_diagnostics_default_off_and_toggle(make_client):
    c = make_client()
    v = c.get("/api/diagnostics").json()
    assert v["trace_claude"] is False and v["trace_garmin"] is False
    assert v["logs_dir"].endswith("logs") and v["can_open"] is False
    v = c.put("/api/diagnostics", json={"trace_claude": True}).json()
    assert v["trace_claude"] is True and v["trace_garmin"] is False
    assert load_settings().trace_claude is True

def test_settings_put_keeps_trace_flags(make_client):
    c = make_client()
    c.put("/api/diagnostics", json={"trace_garmin": True})
    c.put("/api/settings", json={"llm_mode": "cli"})
    assert load_settings().trace_garmin is True

# tests/api/test_desktop_routes.py
def test_open_logs_calls_open_folder(<fixture desktop existante>):
    # Desktop construit avec open_folder=opened.append
    assert client.post("/api/logs/open", headers=H).json() == {"status": "ok"}
    assert opened == [logs_dir()]
    assert client.get("/api/diagnostics", headers=H).json()["can_open"] is True

def test_open_logs_refused_from_lan(...):
    # même motif que les tests `local_only` existants du fichier
    assert r.status_code == 403 and r.json()["code"] == "local_only"
```

Reprendre la construction du `Desktop` factice et des clients loopback/LAN déjà présents dans `test_desktop_routes.py`. Vérifier si les en-têtes `H` sont exigés par `make_client` dans `test_app.py` et s'y conformer.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/api -k "diagnostics or open_logs or trace_flags" -v`
Expected: FAIL (404)

- [ ] **Step 3: Implement** les routes et `open_folder` ; ajouter `"/api/diagnostics"` à la liste de chemins de `app.py:109` si cette liste conditionne l'accès (lire son rôle d'abord et l'aligner sur `/api/settings`).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/api tests/desktop -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add coach/api/app.py coach/api/desktop_routes.py coach/desktop/context.py coach/desktop/launcher.py tests/api
git commit -m "feat(api): routes des journaux de diagnostic"
```

---

### Task 5: Carte « Diagnostic » dans Paramètres

**Files:**
- Modify: `web/src/lib/api.ts` (type et méthodes, à côté de `settings`/`saveSettings`)
- Create: `web/src/components/DiagnosticSettings.svelte`
- Create: `web/src/components/DiagnosticSettings.test.ts`
- Modify: `web/src/routes/Setup.svelte` (après `<ClaudeUsage />`)

**Interfaces:**
- Consumes: routes de la Task 4
- Produces:
  - `type DiagnosticsView = { trace_claude: boolean; trace_garmin: boolean; logs_dir: string; can_open: boolean }`
  - `api.diagnostics(): Promise<DiagnosticsView>`, `api.saveDiagnostics(b: Partial<Pick<DiagnosticsView, "trace_claude" | "trace_garmin">>): Promise<DiagnosticsView>`, `api.openLogs(): Promise<{ status: string }>`

Contenu de la carte : `<h2>Diagnostic</h2>`, une phrase « Enregistre le détail des échanges pour comprendre un échec. Les mots de passe et clés sont masqués. », deux cases à cocher libellées exactement « Journal Claude » et « Journal Garmin » (enregistrement immédiat au changement, case revenue à l'état serveur en cas d'erreur, avec `ErrorBanner`), le chemin `logs_dir` affiché, et le bouton « Ouvrir le dossier des journaux » seulement si `can_open`. Si `GET /api/diagnostics` échoue, la carte ne s'affiche pas (comme `ClaudeUsage`).

- [ ] **Step 1: Write the failing tests** (motif `fetch` stubbé de `LanSettings.test.ts`)

```ts
test("affiche les interrupteurs et enregistre un changement", async () => {
  render(DiagnosticSettings);
  const claude = await screen.findByLabelText("Journal Claude");
  expect(claude).not.toBeChecked();
  await fireEvent.click(claude);
  expect(puts).toEqual([{ trace_claude: true }]);
  expect(await screen.findByLabelText("Journal Claude")).toBeChecked();
});

test("bouton d'ouverture seulement si can_open", async () => {
  view.can_open = false;
  render(DiagnosticSettings);
  await screen.findByLabelText("Journal Garmin");
  expect(screen.queryByText("Ouvrir le dossier des journaux")).toBeNull();
});

test("ouvre le dossier", async () => {
  view.can_open = true;
  render(DiagnosticSettings);
  await fireEvent.click(await screen.findByText("Ouvrir le dossier des journaux"));
  expect(opened).toBe(1);
});

test("rétablit la case si l'enregistrement échoue", async () => {
  putStatus = 500;
  render(DiagnosticSettings);
  const garmin = await screen.findByLabelText("Journal Garmin");
  await fireEvent.click(garmin);
  await waitFor(() => expect(garmin).not.toBeChecked());
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npm --prefix web test -- DiagnosticSettings`
Expected: FAIL (composant absent)

- [ ] **Step 3: Implement** le composant, les méthodes `api`, et l'insertion dans `Setup.svelte`. Reprendre les classes CSS des cartes voisines (`LanSettings`, `ClaudeUsage`).

- [ ] **Step 4: Run to verify pass**

Run: `npm --prefix web test`
Expected: PASS (toute la suite, y compris `App.test.ts` et les tests en lecture seule)

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/api.ts web/src/components/DiagnosticSettings.svelte web/src/components/DiagnosticSettings.test.ts web/src/routes/Setup.svelte
git commit -m "feat(web): carte Diagnostic dans les Paramètres"
```

---

### Vérification finale

- [ ] `uv run pytest` et `npm --prefix web test` : tout passe.
- [ ] Lancer l'application, cocher « Journal Claude », lancer une génération de plan, vérifier que `claude.log` contient `requête` avant toute réponse et qu'aucune clé n'y figure.
