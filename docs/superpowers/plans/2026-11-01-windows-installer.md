# Installateur Windows et mise à jour intégrée — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Distribuer CoachCloclo sous Windows avec un installateur classique (sans droits admin), une icône sur le bureau, un lancement sans console, un écran d'accueil qui connecte Claude puis Garmin, une mise à jour en un clic et le mode LAN activable dans les Réglages.

**Architecture:** Un nouveau paquet `coach/desktop/` (lanceur, instance unique, serveur uvicorn relançable, icône de notification, updater, installation/connexion du CLI Claude) est empaqueté par PyInstaller puis Inno Setup. `create_app` reçoit un objet `Desktop` optionnel qui active un routeur dédié (`/api/setup`, `/api/update`, `/api/lan`) ; sous `coach start`, rien ne change. Le front ajoute un écran d'accueil, un bandeau de mise à jour et deux blocs dans les Réglages.

**Tech Stack:** Python 3.12, FastAPI/Starlette 1.10, uvicorn, pystray + Pillow, PyInstaller, Inno Setup 6 ; Svelte 5, TypeScript, Vitest ; GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-01-windows-installer-design.md` (à lire en entier avant toute tâche).

## Global Constraints

- Interface, messages d'erreur, commentaires et docstrings en français, comme le reste du code.
- La wheel ne gagne aucune dépendance : `pyinstaller`, `pystray`, `pillow` vont dans un groupe `desktop` de `[dependency-groups]`. Rien d'autre côté Python ; aucune nouvelle dépendance front.
- `coach start`, `coach start --lan`, `install.ps1`, `install.sh` et la wheel gardent leur comportement, à une exception voulue près : la boucle locale (`127.0.0.1`, `::1`) est dispensée du PIN en mode LAN.
- Aucune fenêtre console en usage normal : tout sous-processus lancé par l'appli sous Windows passe `creationflags=NO_WINDOW` (sauf le repli console de la connexion Claude, §5.2 de la spec).
- Installation par utilisateur : `PrivilegesRequired=lowest`, `DefaultDirName={localappdata}\Programs\CoachCloclo`. Mutex `CoachCloclo.Instance`.
- Ports : 8765, puis 8766 à 8775. Délais : vérification GitHub 10 s, connexion Claude 300 s, attente du mutex par l'installateur 30 s, attente de la nouvelle version par le front 120 s, sondages toutes les 2 s.
- Assets d'une release : `CoachCloclo-Setup-<version>.exe` et `CoachCloclo-Setup-<version>.exe.sha256` (format `sha256sum` : `<hex>  <nom>`). Dépôt `romigour/CoachCloclo`, surchargeable par `COACH_UPDATE_REPO`.
- Arguments de l'installateur silencieux : `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`.
- Journal : `<data_dir>/logs/coachcloclo.log`, rotation 5 × 1 Mo. Port courant : `<data_dir>/desktop.json` (`{"port": int, "pid": int}`).
- Code d'erreur des endpoints réservés au PC : 403 `local_only` (la spec écrit `lan_local_only` pour `/api/lan` ; on unifie en `local_only` et on corrige la spec dans la Tâche 15).
- Commits sans signature ni trailer Claude.
- Vérification complète : `uv run pytest` et `cd web && npm test && npm run build` verts.

## Review Focus

1. **Exécutable sans console** : sous PyInstaller avec `console=False`, `sys.stdout`/`sys.stderr` valent `None` ; uvicorn et `print` plantent si on ne les redirige pas vers le journal avant tout. Attendu : démarrage normal, sortie dans le journal.
2. **CLI `claude` fraîchement installé hors PATH** : le processus de l'appli garde l'ancien PATH ; la génération de plan doit trouver `~\.local\bin\claude.exe` sans redémarrage, sinon « CLI introuvable » juste après une installation réussie.
3. **Appels `claude -p` depuis l'appli fenêtrée** : sans `CREATE_NO_WINDOW`, chaque génération de plan fait clignoter une console. Attendu : aucun flash.
4. **Basculer le mode LAN pendant un import d'historique ou depuis le téléphone** : l'import continue (même objet `app`) ; un `POST /api/lan` venant d'une IP du réseau est refusé (403) même avec un cookie PIN valide.
5. **Mise à jour lancée deux fois ou interrompue** (double clic, réseau coupé pendant le téléchargement, `.sha256` faux) : une seule installation, rien d'installé en cas d'échec, fichier temporaire supprimé, état `failed` avec message et nouvelle tentative possible.

Chaque point a son test dans la tâche qui possède le code : 1 → Tâche 9 ; 2 et 3 → Tâche 2 ; 4 → Tâches 3 et 8 ; 5 → Tâche 6.

---

## Fichiers

Back :
- `coach/version.py` (nouveau) — `app_version`, `parse_version`.
- `coach/proc.py` (nouveau) — `NO_WINDOW`, `find_claude`.
- `coach/llm/provider.py`, `coach/doctor.py` (mod.) — `find_claude`, `NO_WINDOW`.
- `coach/config.py` (mod.) — `Settings.lan_enabled`.
- `coach/api/deps.py` (mod.) — `valid_pin`, `is_loopback`.
- `coach/api/app.py` (mod.) — LAN dynamique, boucle locale sans PIN, `/api/version`, paramètre `desktop`.
- `coach/api/desktop_routes.py` (nouveau) — routeur `/api/setup`, `/api/update`, `/api/lan`.
- `coach/cli.py` (mod.) — `valid_pin`.
- `coach/desktop/__init__.py`, `context.py`, `instance.py`, `logs.py`, `server.py`, `updater.py`, `claude_setup.py`, `tray.py`, `errors.py`, `launcher.py`, `__main__.py` (nouveaux).

Empaquetage et CI :
- `packaging/windows/coachcloclo.spec`, `installer.iss`, `coachcloclo.ico`, `entry.py` (nouveaux).
- `pyproject.toml` (groupe `desktop`, version), `.github/workflows/release.yml`, `.github/workflows/ci.yml` (mod.).

Front :
- `web/src/lib/api.ts` (mod.) — types et appels `setup`, `update`, `lan`, `version`.
- `web/src/components/GarminLogin.svelte` (nouveau, extrait de `Setup.svelte`).
- `web/src/routes/Welcome.svelte` + `Welcome.test.ts` (nouveaux).
- `web/src/components/UpdateBanner.svelte` + test, `web/src/components/UpdateSettings.svelte`, `web/src/components/LanSettings.svelte` + test (nouveaux).
- `web/src/App.svelte`, `web/src/App.test.ts`, `web/src/routes/Setup.svelte` (mod.).

Docs : `README.md`, `ROADMAP.md`, la spec (code `local_only`, résultat du test de la Tâche 1).

---

### Task 1: Test de `claude auth login` sans console

Tâche d'investigation : son livrable est une constante et une note, pas du code de production.

**Files:**
- Create: `coach/desktop/__init__.py` (docstring seule)
- Create: `coach/desktop/claude_setup.py` (la constante seule pour l'instant)

**Interfaces:**
- Produces: `coach.desktop.claude_setup.LOGIN_NEEDS_CONSOLE: bool`

- [ ] **Step 1: Se déconnecter dans un profil de test**

Dans une console, `set CLAUDE_CONFIG_DIR=%TEMP%\claude-probe` (profil vierge, ne touche pas à la connexion de l'utilisateur), puis `claude auth status --json` : attendu `"loggedIn": false`.

- [ ] **Step 2: Lancer la connexion sans console ni entrée standard**

Script jetable dans le scratchpad (pas dans le dépôt) :

```python
import os, subprocess, time
env = dict(os.environ, CLAUDE_CONFIG_DIR=os.path.expandvars(r"%TEMP%\claude-probe"))
p = subprocess.Popen(["claude", "auth", "login", "--claudeai"], env=env,
                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     creationflags=subprocess.CREATE_NO_WINDOW)
print(p.wait(timeout=300)); print(p.stdout.read().decode(errors="replace"))
```

Se connecter dans le navigateur qui s'ouvre. Attendu si le mode sans console fonctionne : code 0, puis `claude auth status --json` (même `CLAUDE_CONFIG_DIR`) renvoie `"loggedIn": true`. Si le navigateur ne s'ouvre pas, si le processus attend un code collé, ou s'il échoue faute de terminal : le repli console est nécessaire.

- [ ] **Step 3: Enregistrer la décision**

Dans `coach/desktop/claude_setup.py` : `LOGIN_NEEDS_CONSOLE = False` (ou `True`), avec un commentaire d'une ligne datant le test et la version du CLI (`claude --version`). Supprimer `%TEMP%\claude-probe`.

- [ ] **Step 4: Commit**

```bash
git add coach/desktop/__init__.py coach/desktop/claude_setup.py
git commit -m "chore(desktop): connexion Claude sans console vérifiée"
```

---

### Task 2: Version, recherche du CLI Claude et sous-processus sans fenêtre

**Files:**
- Create: `coach/version.py`, `coach/proc.py`
- Modify: `coach/llm/provider.py:68-89` (recherche et `creationflags`), `coach/doctor.py:51-56` et `:170-190` (`find_claude`, `NO_WINDOW` pour l'installation du CLI)
- Test: `tests/test_version.py`, `tests/test_proc.py`, `tests/llm/test_provider.py`, `tests/test_doctor.py`

**Interfaces:**
- Produces:
  - `coach.version.app_version() -> str` — `importlib.metadata.version("coachcloclo")`, `"0.0.0"` si le paquet est introuvable.
  - `coach.version.parse_version(v: str) -> tuple[int, int, int]` — accepte un `v` initial ; `ValueError` sinon.
  - `coach.proc.NO_WINDOW: int` — `subprocess.CREATE_NO_WINDOW` sous `win32`, `0` ailleurs.
  - `coach.proc.find_claude(which=shutil.which, home: Path | None = None) -> str | None` — `which("claude")`, sinon `<home>/.local/bin/claude.exe` (Windows) ou `<home>/.local/bin/claude` s'il existe ; `home` vaut `Path.home()` par défaut.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_version.py
def test_parse_version_orders_numerically():
    assert parse_version("v0.10.0") > parse_version("0.9.3")
    assert parse_version("0.2.0") == (0, 2, 0)

@pytest.mark.parametrize("bad", ["", "1.2", "1.2.x", "latest"])
def test_parse_version_rejects(bad):
    with pytest.raises(ValueError):
        parse_version(bad)

def test_app_version_matches_pyproject():
    assert app_version() == tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]

# tests/test_proc.py
def test_find_claude_prefers_path(tmp_path):
    assert find_claude(which=lambda n: "C:/bin/claude.exe", home=tmp_path) == "C:/bin/claude.exe"

def test_find_claude_falls_back_to_local_bin(tmp_path):
    name = "claude.exe" if sys.platform == "win32" else "claude"
    exe = tmp_path / ".local" / "bin" / name
    exe.parent.mkdir(parents=True); exe.write_text("")
    assert find_claude(which=lambda n: None, home=tmp_path) == str(exe)

def test_find_claude_absent(tmp_path):
    assert find_claude(which=lambda n: None, home=tmp_path) is None

# tests/llm/test_provider.py (ajouts)
def test_cli_runs_without_window():
    run = fake_run(stdout=OK_ENVELOPE)          # enveloppe valide déjà utilisée dans ce fichier
    cli(run).complete("s", "p")
    assert run.kwargs["creationflags"] == NO_WINDOW

def test_cli_found_in_local_bin_when_not_on_path(tmp_path, monkeypatch):
    # which renvoie None mais ~/.local/bin/claude(.exe) existe : l'appel part quand même
    ...
    assert run.args[0] == str(exe)

# tests/test_doctor.py (ajout)
def test_claude_cli_check_finds_local_bin(tmp_path, monkeypatch): ...  # ok=True, détail = chemin
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `uv run pytest tests/test_version.py tests/test_proc.py tests/llm/test_provider.py tests/test_doctor.py -q`
Expected: FAIL (`ModuleNotFoundError: coach.version`, `coach.proc`).

- [ ] **Step 3: Implémenter**

`coach/version.py`, `coach/proc.py` selon les interfaces. `ClaudeCliProvider.complete` remplace `self.which(self.executable)` par `find_claude(self.which)` et passe `creationflags=NO_WINDOW` au `runner`. `doctor._check_claude_cli(which)` et `fix(...claude_auth)` utilisent `find_claude(which)` ; l'installation du CLI (`_INSTALL_WINDOWS`) passe `creationflags=NO_WINDOW`. L'appel interactif `runner([exe])` de `claude_auth` reste sans drapeau (il doit garder le terminal).

- [ ] **Step 4: Lancer les tests**

Run: `uv run pytest -q`
Expected: PASS (tous).

- [ ] **Step 5: Commit**

```bash
git add coach/version.py coach/proc.py coach/llm/provider.py coach/doctor.py tests/test_version.py tests/test_proc.py tests/llm/test_provider.py tests/test_doctor.py
git commit -m "feat: version de l'app, CLI claude trouvé hors PATH, sous-processus sans fenêtre"
```

---

### Task 3: Mode LAN dynamique, boucle locale sans PIN, `/api/version`

**Files:**
- Modify: `coach/config.py` (`Settings.lan_enabled: bool = False`)
- Modify: `coach/api/deps.py` (`valid_pin`, `is_loopback`)
- Modify: `coach/api/app.py:198-280` (middlewares), ajout de `GET /api/version`
- Modify: `coach/cli.py:37-44` (`_ask_pin` utilise `valid_pin`)
- Test: `tests/api/test_app.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: `app_version()` (Tâche 2).
- Produces:
  - `coach.api.deps.valid_pin(pin: str) -> bool` — chiffres seulement, longueur 4 à 12.
  - `coach.api.deps.is_loopback(request: Request) -> bool` — `request.client.host` dans `{"127.0.0.1", "::1"}`.
  - `app.state.lan: bool`, lu à chaque requête par `require_pin` et `host_guard` (tous deux toujours enregistrés).
  - `GET /api/version` → `{"version": str}`, accessible sans PIN.

- [ ] **Step 1: Écrire les tests qui échouent**

Les clients « PC » se créent avec `TestClient(app, client=("127.0.0.1", 50000))` ; le client par défaut (`testclient`) joue le téléphone.

```python
def test_lan_loopback_needs_no_pin(...):      # create_app(lan=True) + client 127.0.0.1 : GET /api/status → 200
def test_lan_other_client_needs_pin(...):     # client par défaut : 401 pin_required (non-régression)
def test_lan_toggle_at_runtime(...):          # create_app(lan=False), app.state.lan = True (PIN défini) :
                                              #   client par défaut → 401 ; Host "192.168.1.12:8765" accepté
def test_lan_off_rejects_ip_host(...):        # app.state.lan = False : Host "192.168.1.12:8765" → 400 bad_host
def test_version_endpoint(...):               # GET /api/version == {"version": app_version()}, même en LAN sans PIN
@pytest.mark.parametrize("pin,ok", [("1234", True), ("123456789012", True), ("123", False),
                                    ("1234567890123", False), ("12a4", False), ("", False)])
def test_valid_pin(pin, ok): assert valid_pin(pin) is ok
def test_settings_lan_enabled_default(coach_home): assert load_settings().lan_enabled is False
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `uv run pytest tests/api/test_app.py tests/test_config.py -q`
Expected: FAIL sur les nouveaux tests.

- [ ] **Step 3: Implémenter**

`create_app` pose `app.state.lan = lan` ; `require_pin` est toujours enregistré et ne s'applique que si `request.app.state.lan` et `not is_loopback(request)` ; `/api/auth/pin` et `/api/version` restent exemptés. `host_guard` passe `request.app.state.lan` à `_host_allowed`. `create_app(lan=True)` sans PIN lève toujours `ValueError`.

- [ ] **Step 4: Lancer les tests**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add coach/config.py coach/api/deps.py coach/api/app.py coach/cli.py tests/api/test_app.py tests/test_config.py
git commit -m "feat(api): mode LAN modifiable à chaud, PC dispensé du PIN, /api/version"
```

---

### Task 4: Instance unique, choix du port et journal

**Files:**
- Create: `coach/desktop/instance.py`, `coach/desktop/logs.py`
- Test: `tests/desktop/__init__.py`, `tests/desktop/test_instance.py`, `tests/desktop/test_logs.py`

**Interfaces:**
- Produces:
  - `instance.PORTS: tuple[int, ...] = (8765, *range(8766, 8776))`
  - `instance.pick_port(is_free: Callable[[int], bool] = port_free) -> int` — premier port libre ; `NoFreePort` sinon.
  - `instance.port_free(port: int) -> bool` — bind sur `127.0.0.1`.
  - `instance.write_state(port: int, pid: int) -> None`, `instance.read_state() -> dict | None` — `<data_dir>/desktop.json` ; `None` si absent ou illisible.
  - `instance.acquire_mutex(name: str = "CoachCloclo.Instance") -> object | None` — `None` si déjà détenu ; via `ctypes` `CreateMutexW` + `GetLastError() == 183`. Hors Windows : verrou de fichier `<data_dir>/desktop.lock` (`msvcrt`/`fcntl`), pour que les tests tournent sur Linux.
  - `instance.release_mutex(handle) -> None`
  - `logs.setup_logging() -> Path` — `RotatingFileHandler(<data_dir>/logs/coachcloclo.log, maxBytes=1_000_000, backupCount=5)` sur le logger racine (niveau INFO), y compris `uvicorn`, `uvicorn.error`, `uvicorn.access` ; si `sys.stdout` ou `sys.stderr` vaut `None`, les remplace par un flux texte qui écrit dans le journal. `sys.excepthook` journalise. Renvoie le chemin du journal.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
def test_pick_port_default(): assert pick_port(lambda p: True) == 8765
def test_pick_port_fallback(): assert pick_port(lambda p: p >= 8767) == 8767
def test_pick_port_none_free():
    with pytest.raises(NoFreePort): pick_port(lambda p: False)
def test_state_roundtrip(coach_home): write_state(8766, 42); assert read_state() == {"port": 8766, "pid": 42}
def test_state_corrupt(coach_home): (coach_home / "desktop.json").write_text("{"); assert read_state() is None
def test_mutex_is_exclusive(coach_home):
    h = acquire_mutex("CoachCloclo.Test"); assert h is not None
    assert acquire_mutex("CoachCloclo.Test") is None
    release_mutex(h); h2 = acquire_mutex("CoachCloclo.Test"); assert h2 is not None; release_mutex(h2)
def test_logging_redirects_missing_stdout(coach_home, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None); monkeypatch.setattr(sys, "stderr", None)
    path = setup_logging(); print("bonjour"); logging.getLogger("uvicorn.error").info("prêt")
    flush_handlers()   # helper du test : flush des handlers racine
    text = path.read_text(encoding="utf-8"); assert "bonjour" in text and "prêt" in text
```

Le test du mutex vérifie l'exclusivité dans un même processus : sous Windows, deux `CreateMutexW` du même nom dans un processus renvoient deux handles, le second avec `ERROR_ALREADY_EXISTS` ; c'est bien ce code qu'on teste. `setup_logging` retire ses handlers via une fonction `teardown_logging()` appelée par une fixture, pour ne pas polluer les autres tests.

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `uv run pytest tests/desktop -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implémenter** selon les interfaces.

- [ ] **Step 4: Lancer les tests**

Run: `uv run pytest tests/desktop -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add coach/desktop/instance.py coach/desktop/logs.py tests/desktop
git commit -m "feat(desktop): instance unique, port de repli et journal"
```

---

### Task 5: Serveur uvicorn relançable

**Files:**
- Create: `coach/desktop/server.py`
- Test: `tests/desktop/test_server.py`

**Interfaces:**
- Produces: `class AppServer(app: ASGIApp, port: int)` avec
  - `start(host: str) -> None` — `uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_config=None))` dans un thread démon ; revient quand `server.started` est vrai (attente max 10 s, sinon `RuntimeError`).
  - `restart(host: str) -> None` — `should_exit = True`, `join`, puis `start(host)` ; même `app`, même port.
  - `stop() -> None`
  - `host: str` (hôte courant).

`log_config=None` : uvicorn garde la journalisation posée par `setup_logging`.

- [ ] **Step 1: Écrire le test qui échoue**

```python
def test_restart_keeps_app_and_port():
    app = create_app(lan=False, garmin_factory=..., llm_factory=...)  # fabriques factices de tests/api
    port = free_port()                                                # helper : bind sur le port 0
    srv = AppServer(app, port); srv.start("127.0.0.1")
    app.state.marker = "même app"
    assert httpx.get(f"http://127.0.0.1:{port}/api/version").status_code == 200
    srv.restart("0.0.0.0")
    assert srv.host == "0.0.0.0"
    assert httpx.get(f"http://127.0.0.1:{port}/api/version").status_code == 200
    assert app.state.marker == "même app"
    srv.stop()
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `uv run pytest tests/desktop/test_server.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implémenter** `AppServer`.

- [ ] **Step 4: Lancer**

Run: `uv run pytest tests/desktop/test_server.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add coach/desktop/server.py tests/desktop/test_server.py
git commit -m "feat(desktop): serveur uvicorn relançable sur un autre hôte"
```

---

### Task 6: Updater

**Files:**
- Create: `coach/desktop/updater.py`
- Test: `tests/desktop/test_updater.py`

**Interfaces:**
- Consumes: `parse_version` (Tâche 2).
- Produces:
  - `DEFAULT_REPO = "romigour/CoachCloclo"` ; `repo_from_env() -> str` (`COACH_UPDATE_REPO` ou `DEFAULT_REPO`).
  - `INSTALLER_ARGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]`
  - `@dataclass UpdateInfo(version: str, installer_url: str, sha256_url: str)`
  - `class UpdateError(Exception)`, `class UpdateBusy(Exception)`
  - `class Updater(current: str, repo: str, fetch_json: Callable[[str], dict], fetch_text: Callable[[str], str], download: Callable[[str, Path, Callable[[int], None]], None], spawn: Callable[[list[str]], None], tmp_dir: Path)` avec :
    - `check() -> UpdateInfo | None` — GET `https://api.github.com/repos/<repo>/releases/latest` ; `None` si version ≤ courante ou si l'un des deux assets manque ; `UpdateError` (message français) sur erreur réseau/JSON ; mémorise `latest`.
    - `view() -> dict` — `{"current", "latest", "available", "state", "progress", "error"}` ; `state` ∈ `idle | checking | downloading | installing | failed`.
    - `install(on_exit: Callable[[], None]) -> None` — synchrone (le routeur l'appelle dans un thread) : `UpdateBusy` si `state` vaut `downloading`/`installing` ; télécharge dans `tmp_dir`, compare le SHA-256 au premier mot du `.sha256` (insensible à la casse), lance `spawn([exe, *INSTALLER_ARGS])`, puis `on_exit()`. En cas d'échec : fichier supprimé, `state = "failed"`, `error` renseigné, `on_exit` jamais appelé.
  - `default_updater(current: str) -> Updater` — implémentations réelles : `urllib.request` (délai 10 s, en-tête `User-Agent: CoachCloclo`), téléchargement par blocs de 64 Kio avec progression en %, `spawn` = `subprocess.Popen(args, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, close_fds=True)`, `tmp_dir = %TEMP%\CoachCloclo-update`.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
RELEASE = {"tag_name": "v0.3.0", "assets": [
    {"name": "coachcloclo-0.3.0-py3-none-any.whl", "browser_download_url": "u/whl"},
    {"name": "CoachCloclo-Setup-0.3.0.exe", "browser_download_url": "u/exe"},
    {"name": "CoachCloclo-Setup-0.3.0.exe.sha256", "browser_download_url": "u/sha"}]}

def test_check_finds_newer(): assert make(current="0.2.0").check() == UpdateInfo("0.3.0", "u/exe", "u/sha")
def test_check_same_or_older(): assert make(current="0.3.0").check() is None
def test_check_numeric_order(): assert make(current="0.10.0", release=tag("v0.9.0")).check() is None
def test_check_ignores_release_without_installer(): ...  # seulement la wheel → None
def test_check_ignores_release_without_sha(): ...
def test_check_network_error(): ...  # fetch_json lève OSError → UpdateError ; view()["error"] renseigné
def test_check_uses_repo(): ...      # URL appelée contient "repos/moi/fork/releases/latest"
def test_install_happy_path(tmp_path):
    # download écrit b"exe", fetch_text renvoie sha256(b"exe") + "  CoachCloclo-Setup-0.3.0.exe"
    # → spawn appelé avec [chemin, *INSTALLER_ARGS] puis on_exit appelé ; view()["state"] == "installing"
def test_install_bad_hash(tmp_path):
    # → spawn et on_exit jamais appelés, fichier supprimé, state "failed", error contient "corrompu"
def test_install_download_error(tmp_path): ...  # download lève OSError → "failed", fichier absent
def test_install_busy(tmp_path):
    # download bloque sur un threading.Event ; second install() → UpdateBusy
def test_install_retry_after_failure(tmp_path): ...  # après "failed", un nouvel install() repart
def test_progress_reported(tmp_path): ...  # download appelle le rappel avec 50 puis 100 → view()["progress"]
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `uv run pytest tests/desktop/test_updater.py -q`
Expected: FAIL.

- [ ] **Step 3: Implémenter** `updater.py`. L'état est protégé par un `threading.Lock` (lu par `view()` depuis les requêtes HTTP).

- [ ] **Step 4: Lancer**

Run: `uv run pytest tests/desktop/test_updater.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add coach/desktop/updater.py tests/desktop/test_updater.py
git commit -m "feat(desktop): vérification et installation des mises à jour"
```

---

### Task 7: Installation et connexion du CLI Claude

**Files:**
- Modify: `coach/desktop/claude_setup.py`
- Test: `tests/desktop/test_claude_setup.py`

**Interfaces:**
- Consumes: `find_claude`, `NO_WINDOW` (Tâche 2) ; `LOGIN_NEEDS_CONSOLE` (Tâche 1).
- Produces:
  - `INSTALL_CMD = ["powershell", "-NoProfile", "-Command", "irm https://claude.ai/install.ps1 | iex"]`
  - `LOGIN_TIMEOUT_S = 300`
  - `class ClaudeSetup(runner=subprocess.run, popen=subprocess.Popen, find=find_claude, needs_console: bool = LOGIN_NEEDS_CONSOLE, clock=time.monotonic, login_timeout_s: int = LOGIN_TIMEOUT_S)` avec :
    - `status() -> dict` — `{"claude_cli": bool, "claude_auth": bool, "claude_step": "idle"|"installing"|"logging_in"|"failed", "claude_error": str | None}`. `claude_auth` : `[exe, "auth", "status", "--json"]` (`NO_WINDOW`, délai 15 s), vrai si le JSON contient `"loggedIn": true` ; faux sur toute erreur. Si `claude_step == "logging_in"` et que `loggedIn` devient vrai, ou que le délai est dépassé (processus tué, `failed`, « La connexion à Claude a expiré, réessaie »), l'étape est mise à jour ici.
    - `start_install() -> None` — thread : `runner(INSTALL_CMD, creationflags=NO_WINDOW, capture_output=True)` ; code non nul ou `OSError` → `failed` avec message ; sinon `idle`.
    - `start_login() -> None` — `popen([exe, "auth", "login", "--claudeai"], stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, creationflags=NO_WINDOW)` ; si `needs_console`, `creationflags=CREATE_NEW_CONSOLE` et sans redirection. CLI absent → `failed`. Un second appel pendant `logging_in` ne relance rien.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
def test_status_cli_absent(): assert ClaudeSetup(find=lambda: None).status()["claude_cli"] is False
def test_status_logged_in(): ...       # runner renvoie '{"loggedIn": true}' → claude_auth True
def test_status_logged_out(): ...      # '{"loggedIn": false}' → False
def test_status_invalid_json(): ...    # "oops" → False, pas d'exception
def test_status_runs_without_window(): ...  # kwargs["creationflags"] == NO_WINDOW
def test_install_success(): ...        # thread joint → step "idle"
def test_install_failure(): ...        # returncode 1 → step "failed", claude_error non vide
def test_login_spawns_without_console(): ...  # args == [exe, "auth", "login", "--claudeai"], NO_WINDOW, stdin DEVNULL
def test_login_console_fallback(): ...         # needs_console=True → CREATE_NEW_CONSOLE
def test_login_completes(): ...        # après start_login, status() avec loggedIn true → step "idle"
def test_login_times_out(): ...        # horloge avancée de 301 s → proc.kill() appelé, step "failed"
def test_login_not_restarted_while_running(): ...  # deux start_login → un seul popen
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `uv run pytest tests/desktop/test_claude_setup.py -q`
Expected: FAIL.

- [ ] **Step 3: Implémenter** (`find` est appelé sans argument : `functools.partial` dans les tests si besoin ; l'état est protégé par un verrou).

- [ ] **Step 4: Lancer**

Run: `uv run pytest tests/desktop/test_claude_setup.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add coach/desktop/claude_setup.py tests/desktop/test_claude_setup.py
git commit -m "feat(desktop): installation et connexion du CLI Claude sans console"
```

---

### Task 8: Routeur desktop (`/api/setup`, `/api/update`, `/api/lan`)

**Files:**
- Create: `coach/desktop/context.py`, `coach/api/desktop_routes.py`
- Modify: `coach/api/app.py` (`create_app(..., desktop: Desktop | None = None)` inclut le routeur)
- Test: `tests/api/test_desktop_routes.py`

**Interfaces:**
- Consumes: `Updater`, `UpdateBusy`, `UpdateError` (Tâche 6) ; `ClaudeSetup` (Tâche 7) ; `valid_pin`, `is_loopback`, `app.state.lan` (Tâche 3).
- Produces:
  - `@dataclass Desktop(updater: Updater, claude: ClaudeSetup, set_lan: Callable[[bool], None], request_exit: Callable[[], None], lan_addresses: Callable[[], list[str]])` dans `coach/desktop/context.py`.
  - `desktop_router(desktop: Desktop) -> APIRouter` (préfixe `/api`) :

| Endpoint | Réponse | Réservé au PC |
|---|---|---|
| `GET /setup/status` | `ClaudeSetup.status()` + `"garmin": "ok"\|"auth_required"\|"unavailable"` (même calcul que `/api/status`) + `"llm_mode"` | non |
| `POST /setup/claude/install` | `{"status": "started"}` | oui |
| `POST /setup/claude/login` | `{"status": "started"}` | oui |
| `GET /update` | `Updater.view()` | non |
| `POST /update/check` | `Updater.view()` après `check()` ; `UpdateError` → 502 `update_check_failed` | oui |
| `POST /update/install` | 202 `{"status": "started"}` ; lance `updater.install(desktop.request_exit)` dans un thread ; déjà en cours → 409 `update_running` | oui |
| `GET /lan` | `{"enabled": app.state.lan, "has_pin": bool, "addresses": lan_addresses(), "local": is_loopback(request)}` | non |
| `POST /lan` `{enabled: bool, pin?: str}` | même forme que `GET /lan` | oui |

  - Hors PC : 403 `{"code": "local_only", "detail": "Action possible seulement depuis l'ordinateur où tourne CoachCloclo"}`.
  - `POST /lan` : `pin` fourni et invalide → 422 `invalid_pin` ; activation sans PIN enregistré ni `pin` → 422 `pin_required_to_enable` ; enregistre `pin_hash` (si fourni) et `lan_enabled` ; pose `app.state.lan` ; à la désactivation, vide `app.state.sessions` ; appelle `desktop.set_lan(enabled)` via `threading.Timer(0.5, …)` pour que la réponse parte avant la relance.
  - `coach.desktop.context.lan_addresses(port: int) -> list[str]` — IPv4 de `socket.getaddrinfo(socket.gethostname(), None, AF_INET)`, privées (`ipaddress.ip_address(a).is_private`), hors `127.*` et `169.254.*`, dédupliquées et triées, au format `http://<ip>:<port>`.

- [ ] **Step 1: Écrire les tests qui échouent**

Fixture `desktop_app(fake_updater, fake_claude)` : `create_app(lan=False, ..., desktop=Desktop(...))` avec des faux enregistrant leurs appels ; `pc = TestClient(app, client=("127.0.0.1", 50000))`, `phone = TestClient(app)`. Les `POST` envoient `X-Coach: 1`.

```python
def test_desktop_routes_absent_without_desktop(make_client): assert make_client().get("/api/update").status_code == 404
def test_setup_status(pc): ...              # claude_cli/claude_auth/claude_step/garmin/llm_mode présents
@pytest.mark.parametrize("path", ["/api/setup/claude/install", "/api/setup/claude/login",
                                  "/api/update/check", "/api/update/install", "/api/lan"])
def test_phone_cannot_act(phone_with_pin_cookie, path):
    # app.state.lan = True, téléphone authentifié par PIN : POST → 403 local_only
def test_update_install_starts_and_exits(pc): ...  # 202 ; le faux updater reçoit request_exit
def test_update_install_conflict(pc): ...          # faux updater lève UpdateBusy → 409 update_running
def test_update_check_error(pc): ...               # UpdateError → 502
def test_lan_enable_requires_pin(pc): ...          # {"enabled": true} sans PIN existant → 422 pin_required_to_enable
def test_lan_enable_with_pin(pc):
    # {"enabled": true, "pin": "1234"} → 200, settings.lan_enabled, verify_pin("1234", pin_hash),
    # app.state.lan True, set_lan(True) appelé (attendre le Timer : set_lan pose un threading.Event)
def test_lan_invalid_pin(pc): ...                  # "12" → 422 invalid_pin, rien d'enregistré
def test_lan_disable_clears_sessions(pc): ...      # app.state.sessions vidé, set_lan(False)
def test_lan_view_from_phone_is_read_only(phone_with_pin_cookie): ...  # GET /api/lan → local False
def test_lan_toggle_keeps_history_runner(pc): ...  # app.state.history identique avant/après
def test_lan_addresses_filters(monkeypatch): ...   # getaddrinfo factice → seules les IP privées, hors 169.254
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `uv run pytest tests/api/test_desktop_routes.py -q`
Expected: FAIL.

- [ ] **Step 3: Implémenter.** Réponses d'erreur au format existant `{"code", "detail"}` via un `JSONResponse` local au module (pas d'import de `coach.api.app`, qui importe ce module). Le calcul de `garmin` est factorisé dans `app.py` en `def garmin_state(factory) -> str` et réutilisé par `/api/status` et `/setup/status`.

- [ ] **Step 4: Lancer**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add coach/desktop/context.py coach/api/desktop_routes.py coach/api/app.py tests/api/test_desktop_routes.py
git commit -m "feat(api): endpoints de configuration, de mise à jour et du mode LAN"
```

---

### Task 9: Lanceur, icône de notification et erreurs fatales

**Files:**
- Create: `coach/desktop/launcher.py`, `coach/desktop/tray.py`, `coach/desktop/errors.py`, `coach/desktop/__main__.py`
- Modify: `pyproject.toml` (groupe `desktop = ["pyinstaller", "pystray", "pillow"]`)
- Test: `tests/desktop/test_launcher.py`

**Interfaces:**
- Consumes: tout `coach/desktop/` ; `create_app`, `Desktop`, `lan_addresses` ; `load_settings`.
- Produces:
  - `launcher.main(argv: list[str] | None = None) -> int` :
    1. `setup_logging()` en premier (Review Focus 1).
    2. `acquire_mutex()` ; déjà détenu → `read_state()` : port présent et `GET http://127.0.0.1:<port>/api/version` répond en 3 s → `webbrowser.open`, retour 0 ; sinon `fatal("CoachCloclo semble bloqué : quitte-le depuis l'icône près de l'horloge ou redémarre l'ordinateur")`, retour 1.
    3. `pick_port()` (`NoFreePort` → `fatal("Aucun port libre entre 8765 et 8775", log)`), `write_state(port, os.getpid())`.
    4. `settings = load_settings()` ; LAN au démarrage seulement si `lan_enabled` **et** `pin_hash`.
    5. `create_app(lan=…, garmin_factory=…, llm_factory=…, desktop=Desktop(...))` (mêmes fabriques que `coach start`) ; `AppServer(app, port).start("0.0.0.0" if lan else "127.0.0.1")`.
    6. `--smoke` : `GET /api/version`, compare à `app_version()`, arrête le serveur, retour 0 (1 si écart) — ni icône ni navigateur ni vérification de mise à jour.
    7. Sinon : thread de vérification de mise à jour (`updater.check()`, erreurs journalisées ; si une version est trouvée, `tray.notify("Version x.y.z de CoachCloclo disponible")`) ; ouverture du navigateur ; `Tray(...).run()` bloquant ; à la sortie (`Quitter` ou `request_exit`) : `server.stop()`, `release_mutex`, retour 0.
    8. Toute exception non rattrapée : `fatal(str(e), log)`, retour 1.
  - `errors.fatal(message: str, log_path: Path | None = None) -> None` — `ctypes.windll.user32.MessageBoxW(None, texte, "CoachCloclo", 0x10)` sous Windows (texte suivi de « Journal : <chemin> »), sinon `print` sur stderr.
  - `tray.Tray(open_app: Callable[[], None], check_updates: Callable[[], str], quit_app: Callable[[], None])` avec `run()`, `stop()`, `notify(message: str)` ; menu « Ouvrir CoachCloclo » (action par défaut), « Vérifier les mises à jour » (bulle avec le texte renvoyé : « CoachCloclo est à jour », « Version x.y.z disponible » ou l'erreur), « Quitter ». Icône : `packaging/windows/coachcloclo.ico` chargé via `Pillow` depuis les ressources embarquées (`sys._MEIPASS`) ou le dépôt.
  - `request_exit` (passé à `Desktop`) appelle `tray.stop()` depuis n'importe quel thread.
  - `__main__.py` : `raise SystemExit(main())`.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
def test_smoke_mode_returns_zero(coach_home, monkeypatch):
    monkeypatch.setattr(instance, "PORTS", (free_port(),))
    assert launcher.main(["--smoke"]) == 0
    assert (coach_home / "logs" / "coachcloclo.log").exists()

def test_second_instance_opens_browser(coach_home, monkeypatch):
    # acquire_mutex → None ; read_state → port d'un AppServer de test démarré ; webbrowser.open capturé
    assert launcher.main([]) == 0 and opened == [f"http://127.0.0.1:{port}"]

def test_second_instance_stuck(coach_home, monkeypatch):
    # acquire_mutex → None ; read_state → port sans serveur ; fatal capturé
    assert launcher.main([]) == 1 and "bloqué" in fatal_messages[0]

def test_no_free_port(coach_home, monkeypatch):
    monkeypatch.setattr(instance, "port_free", lambda p: False)
    assert launcher.main(["--smoke"]) == 1 and "Aucun port libre" in fatal_messages[0]

def test_lan_not_started_without_pin(coach_home, monkeypatch):
    # settings lan_enabled=True, pin_hash=None → AppServer.start reçoit "127.0.0.1"
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `uv run pytest tests/desktop/test_launcher.py -q`
Expected: FAIL.

- [ ] **Step 3: Implémenter**, puis `uv sync --group desktop`.

- [ ] **Step 4: Lancer les tests puis l'appli à la main**

Run: `uv run pytest -q` → PASS.
Run: `uv run --group desktop python -m coach.desktop` → l'onglet s'ouvre, l'icône apparaît, « Quitter » arrête tout ; une seconde commande pendant que la première tourne ouvre un onglet et rend la main.

- [ ] **Step 5: Commit**

```bash
git add coach/desktop pyproject.toml uv.lock tests/desktop/test_launcher.py
git commit -m "feat(desktop): lanceur sans console avec icône de notification"
```

---

### Task 10: Empaquetage PyInstaller et installateur Inno Setup

**Files:**
- Create: `packaging/windows/entry.py` (`from coach.desktop.launcher import main; raise SystemExit(main())`)
- Create: `packaging/windows/coachcloclo.spec`, `packaging/windows/installer.iss`, `packaging/windows/coachcloclo.ico` (16, 32, 48, 256 px, générée avec Pillow à partir de `web/public/icon-512.png`)
- Modify: `.gitignore` (`build/`, `dist/`, `packaging/windows/Output/`)

**Interfaces:**
- Consumes: `launcher.main` (Tâche 9), `coach/web_dist/` (`npm run build`).
- Produces: `dist/CoachCloclo/CoachCloclo.exe` ; `packaging/windows/Output/CoachCloclo-Setup-<version>.exe`.

`coachcloclo.spec` : `Analysis(["packaging/windows/entry.py"], datas=[("coach/web_dist", "coach/web_dist"), ("packaging/windows/coachcloclo.ico", ".")] + copy_metadata("coachcloclo"), hiddenimports=collect_submodules("uvicorn") + ["pystray._win32"])` ; `EXE(name="CoachCloclo", console=False, icon="packaging/windows/coachcloclo.ico")` ; `COLLECT(name="CoachCloclo")` (mode dossier).

`installer.iss` (valeurs de la spec §4.4) :
- `[Setup]` : `AppId={{8F3C2B1E-6A4D-4E7B-9C21-5D0E7A1B3C44}`, `AppName=CoachCloclo`, `AppVersion={#AppVersion}`, `DefaultDirName={localappdata}\Programs\CoachCloclo`, `PrivilegesRequired=lowest`, `DisableProgramGroupPage=yes`, `OutputBaseFilename=CoachCloclo-Setup-{#AppVersion}`, `SetupIconFile=coachcloclo.ico`, `UninstallDisplayIcon={app}\CoachCloclo.exe`, `WizardStyle=modern`.
- `[Languages]` : `french` (`compiler:Languages\French.isl`).
- `[Tasks]` : `desktopicon` sans `Flags: unchecked` (cochée par défaut).
- `[Files]` : `..\..\dist\CoachCloclo\*` → `{app}`, `recursesubdirs ignoreversion`.
- `[Icons]` : menu Démarrer `{autoprograms}\CoachCloclo`, bureau `{autodesktop}\CoachCloclo` (tâche `desktopicon`).
- `[Run]` : `Filename: {app}\CoachCloclo.exe; Flags: nowait postinstall` (pas de `skipifsilent`).
- `[UninstallDelete]` : rien (les données sont dans `%LOCALAPPDATA%\CoachCloclo`, jamais sous `{app}`).
- `[Code]` : `InitializeSetup` attend jusqu'à 30 s (pas de 500 ms) que `CheckForMutexes('CoachCloclo.Instance')` soit faux ; au-delà, `Result := False`. `InitializeUninstall` : même attente, puis message « Quitte CoachCloclo avant de le désinstaller » si toujours détenu.

- [ ] **Step 1: Construire l'exécutable**

Run: `cd web && npm run build && cd .. && uv run --group desktop pyinstaller --noconfirm packaging/windows/coachcloclo.spec`
Expected: `dist/CoachCloclo/CoachCloclo.exe` existe.

- [ ] **Step 2: Test de fumée de l'exécutable**

Run: `dist\CoachCloclo\CoachCloclo.exe --smoke; echo $LASTEXITCODE` (PowerShell ; `Start-Process -Wait -PassThru` puisque l'exe est fenêtré)
Expected: code 0 ; `%LOCALAPPDATA%\CoachCloclo\CoachCloclo\logs\coachcloclo.log` contient le démarrage d'uvicorn.

- [ ] **Step 3: Compiler l'installateur**

Run: `iscc /DAppVersion=0.2.0 packaging\windows\installer.iss` (Inno Setup 6 installé localement : `winget install JRSoftware.InnoSetup`)
Expected: `packaging/windows/Output/CoachCloclo-Setup-0.2.0.exe`.

- [ ] **Step 4: Installer, lancer, désinstaller sur ce poste**

Installation sans UAC, icône du bureau, lancement en fin d'installation, désinstallation depuis « Applications » ; le dossier de données est intact. Puis `CoachCloclo-Setup-0.2.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART` pendant que l'appli tourne et qu'on la quitte dans les 30 s : l'installation passe et relance l'appli.

- [ ] **Step 5: Commit**

```bash
git add packaging/windows .gitignore
git commit -m "build(windows): exécutable PyInstaller et installateur Inno Setup"
```

---

### Task 11: Écran d'accueil (front)

**Files:**
- Modify: `web/src/lib/api.ts` (types et appels)
- Create: `web/src/components/GarminLogin.svelte` (formulaire email / mot de passe / MFA extrait de `Setup.svelte`, événement `onconnected`)
- Modify: `web/src/routes/Setup.svelte` (utilise `GarminLogin` ; lien « Assistant de configuration » vers `#/welcome` si `setupStatus` existe)
- Create: `web/src/routes/Welcome.svelte`, `web/src/routes/Welcome.test.ts`
- Modify: `web/src/App.svelte`, `web/src/App.test.ts`, `web/src/components/ErrorBanner.svelte`

**Interfaces:**
- Consumes: `GET /api/setup/status`, `POST /api/setup/claude/install`, `POST /api/setup/claude/login` (Tâche 8).
- Produces (dans `api.ts`) :
  - `type SetupStatus = { claude_cli: boolean; claude_auth: boolean; claude_step: "idle" | "installing" | "logging_in" | "failed"; claude_error: string | null; garmin: "ok" | "auth_required" | "unavailable"; llm_mode: "cli" | "api" }`
  - `api.setupStatus(): Promise<SetupStatus | null>` — `null` sur 404 (sous `coach start`).
  - `api.installClaude()`, `api.loginClaude()` : `Promise<{ status: string }>`.
  - `function setupDone(s: SetupStatus, claudeSkipped: boolean): boolean` — `garmin === "ok"` et (`llm_mode === "api"` ou `claude_auth` ou `claudeSkipped`).
  - Route `"welcome"` ajoutée à `ROUTES` ; clé `localStorage` `coach.claudeSkipped` (`"1"`).

Comportement (`Welcome.svelte`, textes de la spec §5) : étape Claude tant que `llm_mode === "cli"`, `!claude_auth` et non passée ; sinon étape Garmin. Sondage de `setupStatus` toutes les 2 s pendant `installing`/`logging_in`. Boutons : « Installer Claude », « Se connecter à Claude », « Réessayer » (si `failed`, avec `claude_error`), « Passer pour l'instant ». Étape Garmin = `GarminLogin` ; à la connexion, `onconnected` de l'App (synchro puis page d'accueil). Accès à `localStorage` sous `try/catch`.

`ErrorBanner.svelte` : pour le code `llm_unavailable` (503, déjà renvoyé par l'API quand Claude n'est pas connecté), le message est suivi d'un lien « Connecte Claude » vers `#/welcome`, affiché seulement si `api.setupStatus()` n'a pas renvoyé `null` (prop `setupAvailable` passée par l'App).

Dans `App.svelte`, `start()` appelle `api.setupStatus()` ; si non `null` et `!setupDone(...)`, `location.hash = "#/welcome"` au lieu de `home()`. Un appel `/api/status` en échec n'empêche pas l'écran d'accueil.

- [ ] **Step 1: Écrire les tests qui échouent**

```ts
// Welcome.test.ts (fetch simulé comme dans Today.test.ts)
it("propose d'installer Claude quand le CLI est absent")              // bouton visible ; clic → POST /api/setup/claude/install
it("affiche la progression puis le bouton de connexion")               // installing → idle + claude_cli true
it("affiche l'erreur et Réessayer quand l'installation échoue")
it("lance la connexion et passe à Garmin une fois connecté")           // logging_in → claude_auth true → formulaire Garmin
it("Passer pour l'instant mène à Garmin et est mémorisé")              // localStorage coach.claudeSkipped = "1"
it("saute l'étape Claude en mode clé API")
// App.test.ts
it("redirige vers l'écran d'accueil si la configuration est incomplète")
it("ne montre pas l'écran d'accueil sous coach start (404)")
it("revient à l'étape Garmin quand la connexion Garmin a expiré")      // garmin auth_required, Claude ok
it("propose Connecte Claude quand la génération échoue faute de Claude") // 503 llm_unavailable → lien #/welcome
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `cd web && npx vitest run src/routes/Welcome.test.ts src/App.test.ts`
Expected: FAIL.

- [ ] **Step 3: Implémenter.** Les tests existants de `Setup.svelte` (connexion Garmin) doivent rester verts après l'extraction de `GarminLogin`.

- [ ] **Step 4: Lancer**

Run: `cd web && npm test && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src
git commit -m "feat(web): écran d'accueil Claude puis Garmin"
```

---

### Task 12: Bandeau et réglages de mise à jour (front)

**Files:**
- Modify: `web/src/lib/api.ts`
- Create: `web/src/components/UpdateBanner.svelte`, `web/src/components/UpdateBanner.test.ts`, `web/src/components/UpdateSettings.svelte`
- Modify: `web/src/App.svelte` (bandeau), `web/src/routes/Setup.svelte` (bloc « Mise à jour »)

**Interfaces:**
- Consumes: `GET /api/update`, `POST /api/update/check`, `POST /api/update/install`, `GET /api/version` (Tâches 3 et 8).
- Produces:
  - `type UpdateView = { current: string; latest: string | null; available: boolean; state: "idle" | "checking" | "downloading" | "installing" | "failed"; progress: number; error: string | null }`
  - `api.update(): Promise<UpdateView | null>` (`null` sur 404), `api.checkUpdate()`, `api.installUpdate()`, `api.version(): Promise<{ version: string }>`.
  - `async function waitForVersion(from: string, opts?: { intervalMs?: number; timeoutMs?: number; now?: () => number }): Promise<boolean>` dans `web/src/lib/update.ts` — sonde `api.version()` toutes les 2 s (erreurs réseau ignorées), `true` dès que la version diffère de `from`, `false` après 120 s.
  - Clé `localStorage` `coach.updateDismissed` = version masquée.

`UpdateBanner` : charge `api.update()` au montage et après 5 s (laisse le temps à la vérification du lancement) ; visible si `available` et `latest !== dismissed`. « Mettre à jour » → `installUpdate()`, puis « Téléchargement… <progress> % » (sondage 1 s) → « Mise à jour en cours, CoachCloclo va redémarrer… » → `waitForVersion(current)` → `location.reload()` ; `false` → « La mise à jour semble bloquée : relance CoachCloclo depuis l'icône du bureau ». `failed` → message + « Réessayer ». « Plus tard » → mémorise `latest`.

`UpdateSettings` (Réglages) : « Version installée : x.y.z », bouton « Vérifier les mises à jour » → « CoachCloclo est à jour » / « Version x.y.z disponible » + bouton « Mettre à jour » (même flux) / erreur. Masqué si `api.update()` vaut `null`.

- [ ] **Step 1: Écrire les tests qui échouent**

```ts
it("affiche le bandeau quand une version est disponible")
it("Plus tard masque cette version, la suivante réapparaît")
it("montre la progression puis recharge quand la nouvelle version répond")   // location.reload espionné
it("signale une mise à jour bloquée après le délai")                           // now() simulé
it("affiche l'erreur et Réessayer en cas d'échec")
it("waitForVersion ignore les erreurs réseau pendant le redémarrage")
it("le bouton des Réglages affiche À jour")
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `cd web && npx vitest run src/components/UpdateBanner.test.ts`
Expected: FAIL.

- [ ] **Step 3: Implémenter.**

- [ ] **Step 4: Lancer**

Run: `cd web && npm test && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src
git commit -m "feat(web): bandeau et réglages de mise à jour"
```

---

### Task 13: Mode LAN dans les Réglages (front)

**Files:**
- Modify: `web/src/lib/api.ts`
- Create: `web/src/components/LanSettings.svelte`, `web/src/components/LanSettings.test.ts`
- Modify: `web/src/routes/Setup.svelte`

**Interfaces:**
- Consumes: `GET /api/lan`, `POST /api/lan` (Tâche 8).
- Produces:
  - `type LanView = { enabled: boolean; has_pin: boolean; addresses: string[]; local: boolean }`
  - `api.lan(): Promise<LanView | null>` (`null` sur 404), `api.setLan(enabled: boolean, pin?: string): Promise<LanView>`.

Bloc « Accès depuis ton téléphone » (textes de la spec §7.1) : interrupteur ; si `!has_pin` à l'activation (ou « Changer le PIN »), deux champs PIN (`inputmode="numeric"`, validation 4 à 12 chiffres et égalité côté front avant l'envoi) ; avertissement pare-feu affiché avant l'envoi de l'activation ; une fois activé, les adresses avec « Copier » (`navigator.clipboard.writeText`, sous `try/catch`) et l'aide pare-feu. Après `setLan`, attendre 1 s puis relire `api.lan()` (le serveur relance son écoute). `local === false` : tout en lecture seule avec « Modifiable seulement depuis l'ordinateur ». Masqué si `api.lan()` vaut `null`. Erreurs `invalid_pin` / `pin_required_to_enable` affichées sous les champs.

- [ ] **Step 1: Écrire les tests qui échouent**

```ts
it("demande un PIN à la première activation et l'envoie")          // POST /api/lan {enabled: true, pin: "1234"}
it("refuse deux PIN différents ou trop courts sans appeler l'API")
it("affiche les adresses une fois activé")
it("désactive sans demander de PIN")
it("est en lecture seule depuis un téléphone")
it("affiche l'avertissement pare-feu avant l'activation")
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `cd web && npx vitest run src/components/LanSettings.test.ts`
Expected: FAIL.

- [ ] **Step 3: Implémenter.**

- [ ] **Step 4: Lancer**

Run: `cd web && npm test && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src
git commit -m "feat(web): mode LAN activable dans les Réglages"
```

---

### Task 14: CI et release

**Files:**
- Modify: `.github/workflows/release.yml`, `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `packaging/windows/*` (Tâche 10), `--smoke` (Tâche 9).
- Produces: releases contenant la wheel, `CoachCloclo-Setup-<v>.exe` et `.sha256`.

`release.yml` (spec §9.1) :
- `on: push: tags: ["v*"]` et `workflow_dispatch`.
- Job `build` (ubuntu, étapes actuelles) + `actions/upload-artifact@v4` : `wheel` (`dist/*.whl`) et `web_dist` (`coach/web_dist/`).
- Job `windows` (`windows-latest`, `needs: build`) : checkout, `setup-uv`, `download-artifact` `web_dist` → `coach/web_dist`, `uv sync --group desktop`, `uv run pyinstaller --noconfirm packaging/windows/coachcloclo.spec`, test de fumée (`$p = Start-Process dist\CoachCloclo\CoachCloclo.exe -ArgumentList '--smoke' -Wait -PassThru; if ($p.ExitCode -ne 0) { Get-Content $env:LOCALAPPDATA\CoachCloclo\CoachCloclo\logs\coachcloclo.log; exit 1 }`), version lue dans `pyproject.toml` (et égale au tag sans `v` lors d'un push de tag, sinon échec), `if (-not (Get-Command iscc -ErrorAction SilentlyContinue)) { choco install innosetup -y }`, `iscc /DAppVersion=$v packaging\windows\installer.iss`, fichier `.sha256` au format `<hex>  <nom>` (`(Get-FileHash -Algorithm SHA256).Hash.ToLower()`, encodage ASCII), `upload-artifact` `installer`.
- Job `publish` (ubuntu, `needs: [build, windows]`, `if: startsWith(github.ref, 'refs/tags/v')`) : télécharge les artefacts, `gh release create "$GITHUB_REF_NAME" wheel/*.whl installer/* --title "CoachCloclo $GITHUB_REF_NAME" --generate-notes`.

`ci.yml` : job supplémentaire `pytest-windows` (`windows-latest`) : `setup-uv`, `uv run pytest` (le front n'est pas nécessaire aux tests Python).

- [ ] **Step 1: Valider la syntaxe**

Run: `uvx --from check-jsonschema check-jsonschema --builtin-schema vendor.github-workflows .github/workflows/release.yml .github/workflows/ci.yml`
Expected: `ok -- validation done`.

- [ ] **Step 2: Commit et push de la branche**

```bash
git add .github/workflows
git commit -m "ci: installateur Windows dans la release et tests sous Windows"
git push -u origin HEAD
```

- [ ] **Step 3: Déclencher le workflow à la main sur la branche**

Run: `gh workflow run release.yml --ref <branche>` puis `gh run watch`
Expected: `build` et `windows` verts, `publish` ignoré ; l'artefact `installer` contient l'exe et son `.sha256`. Vérifier : `ci.yml` vert, y compris `pytest-windows`.

---

### Task 15: Documentation, version 0.2.0 et vérification en conditions réelles

**Files:**
- Modify: `README.md`, `ROADMAP.md`, `pyproject.toml` (`version = "0.2.0"`), `uv.lock`, `docs/superpowers/specs/2026-11-01-windows-installer-design.md`

- [ ] **Step 1: Mettre à jour la documentation**

README : la section « Installation » commence par « Windows : télécharge `CoachCloclo-Setup-x.y.z.exe` depuis la dernière release », avec l'avertissement SmartScreen (« Informations complémentaires » → « Exécuter quand même ») ; le script PowerShell passe sous « Installation avancée (terminal) ». Ajouter « Mise à jour » (bandeau, icône, Réglages) et « Mode LAN depuis les Réglages » ; préciser que le PC n'a plus besoin du PIN. « Publier une version » mentionne l'installateur et le déclenchement manuel. ROADMAP : entrée cochée « Installateur Windows avec mise à jour intégrée ». Spec : `lan_local_only` → `local_only`, résultat de la Tâche 1 dans le §5.2.

- [ ] **Step 2: Version**

`version = "0.2.0"` dans `pyproject.toml`, puis `uv lock`.

- [ ] **Step 3: Vérification complète**

Run: `uv run pytest -q` puis `cd web && npm test && npm run build`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add README.md ROADMAP.md pyproject.toml uv.lock docs/superpowers/specs/2026-11-01-windows-installer-design.md
git commit -m "docs: installation Windows par installateur, version 0.2.0"
```

- [ ] **Step 5: Vérification en conditions réelles**

Sur Windows Sandbox avec l'installateur de l'artefact de la Tâche 14 (relancé après ce commit), dérouler la liste de contrôle du §10.3 de la spec. Pour la mise à jour : publier sur un fork une release `v0.2.1` (installateur + `.sha256`), lancer l'appli 0.2.0 avec `COACH_UPDATE_REPO=<fork>`. Noter chaque point coché ou en échec dans la description de la PR (préfixe 🧪 tant que la liste n'est pas entièrement verte).
