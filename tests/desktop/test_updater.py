import hashlib
import threading

import pytest

from coach.desktop.updater import (
    INSTALLER_ARGS,
    UpdateBusy,
    UpdateError,
    UpdateInfo,
    Updater,
    repo_from_env,
)

RELEASE = {
    "tag_name": "v0.3.0",
    "assets": [
        {"name": "coachcloclo-0.3.0-py3-none-any.whl", "browser_download_url": "u/whl"},
        {"name": "CoachCloclo-Setup-0.3.0.exe", "browser_download_url": "u/exe"},
        {"name": "CoachCloclo-Setup-0.3.0.exe.sha256", "browser_download_url": "u/sha"},
    ],
}


def tag(t: str) -> dict:
    return {**RELEASE, "tag_name": t}


def sha_text(data: bytes, name: str = "CoachCloclo-Setup-0.3.0.exe") -> str:
    return f"{hashlib.sha256(data).hexdigest()}  {name}\n"


class Env:
    def __init__(self, tmp_path, current, release, content, sha, download=None):
        self.urls: list[str] = []
        self.spawned: list[list[str]] = []
        self.exited = 0
        self.release = release
        self.content = content
        self.sha = sha
        self.custom_download = download

        def fetch_json(url):
            self.urls.append(url)
            if isinstance(self.release, Exception):
                raise self.release
            return self.release

        def fetch_text(url):
            return self.sha

        def download(url, dest, progress):
            if self.custom_download:
                return self.custom_download(url, dest, progress)
            dest.write_bytes(self.content)

        self.updater = Updater(
            current=current,
            repo="moi/fork",
            fetch_json=fetch_json,
            fetch_text=fetch_text,
            download=download,
            spawn=self.spawned.append,
            tmp_dir=tmp_path / "tmp",
        )

    def on_exit(self):
        self.exited += 1


def make(tmp_path, current="0.2.0", release=RELEASE, content=b"exe", sha=None, download=None):
    if sha is None:
        sha = sha_text(content)
    return Env(tmp_path, current, release, content, sha, download)


def test_check_finds_newer(tmp_path):
    assert make(tmp_path).updater.check() == UpdateInfo("0.3.0", "u/exe", "u/sha")


def test_check_same_or_older(tmp_path):
    assert make(tmp_path, current="0.3.0").updater.check() is None


def test_check_numeric_order(tmp_path):
    assert make(tmp_path, current="0.10.0", release=tag("v0.9.0")).updater.check() is None


def test_check_ignores_release_without_installer(tmp_path):
    rel = {**RELEASE, "assets": [RELEASE["assets"][0], RELEASE["assets"][2]]}
    assert make(tmp_path, release=rel).updater.check() is None


def test_check_ignores_release_without_sha(tmp_path):
    rel = {**RELEASE, "assets": RELEASE["assets"][:2]}
    assert make(tmp_path, release=rel).updater.check() is None


def test_check_unparsable_tag_is_no_update(tmp_path):
    assert make(tmp_path, release=tag("nightly")).updater.check() is None


def test_check_network_error(tmp_path):
    env = make(tmp_path, release=OSError("pas de réseau"))
    with pytest.raises(UpdateError):
        env.updater.check()
    assert "Impossible de vérifier les mises à jour" in env.updater.view()["error"]
    assert env.updater.view()["state"] == "idle"


def test_check_bad_json(tmp_path):
    env = make(tmp_path, release={"pas": "une release"})
    with pytest.raises(UpdateError):
        env.updater.check()


def test_check_uses_repo(tmp_path):
    env = make(tmp_path)
    env.updater.check()
    assert "repos/moi/fork/releases/latest" in env.urls[0]


def test_view_after_check(tmp_path):
    env = make(tmp_path)
    env.updater.check()
    v = env.updater.view()
    assert v["current"] == "0.2.0" and v["latest"] == "0.3.0" and v["available"] is True
    assert v["state"] == "idle" and v["progress"] == 0 and v["error"] is None


def test_repo_from_env(monkeypatch):
    monkeypatch.delenv("COACH_UPDATE_REPO", raising=False)
    assert repo_from_env() == "romigour/CoachCloclo"
    monkeypatch.setenv("COACH_UPDATE_REPO", "a/b")
    assert repo_from_env() == "a/b"


def test_install_without_check(tmp_path):
    env = make(tmp_path)
    with pytest.raises(UpdateError, match="Aucune mise à jour disponible"):
        env.updater.install(env.on_exit)
    assert env.updater.view()["state"] == "idle"


def test_install_happy_path(tmp_path):
    env = make(tmp_path)
    env.updater.check()
    env.updater.install(env.on_exit)
    exe = tmp_path / "tmp" / "CoachCloclo-Setup-0.3.0.exe"
    assert env.spawned == [[str(exe), *INSTALLER_ARGS]]
    assert env.exited == 1
    assert env.updater.view()["state"] == "installing"


def test_install_sha_case_insensitive(tmp_path):
    env = make(tmp_path, sha=sha_text(b"exe").upper())
    env.updater.check()
    env.updater.install(env.on_exit)
    assert env.exited == 1


def test_install_bad_hash(tmp_path):
    env = make(tmp_path, sha=sha_text(b"autre chose"))
    env.updater.check()
    env.updater.install(env.on_exit)
    assert env.spawned == [] and env.exited == 0
    assert not (tmp_path / "tmp" / "CoachCloclo-Setup-0.3.0.exe").exists()
    v = env.updater.view()
    assert v["state"] == "failed" and "corrompu" in v["error"]


def test_install_download_error(tmp_path):
    def boom(url, dest, progress):
        dest.write_bytes(b"partiel")
        raise OSError("coupé")

    env = make(tmp_path, download=boom)
    env.updater.check()
    env.updater.install(env.on_exit)
    assert env.spawned == [] and env.exited == 0
    assert not (tmp_path / "tmp" / "CoachCloclo-Setup-0.3.0.exe").exists()
    assert env.updater.view()["state"] == "failed"
    assert env.updater.view()["error"]


def test_install_spawn_error(tmp_path):
    env = make(tmp_path)

    def refuse(args):
        raise OSError("refusé")

    env.updater._spawn = refuse
    env.updater.check()
    env.updater.install(env.on_exit)
    assert env.exited == 0 and env.updater.view()["state"] == "failed"


def blocking_env(tmp_path):
    started, release = threading.Event(), threading.Event()

    def slow(url, dest, progress):
        started.set()
        assert release.wait(5)
        dest.write_bytes(b"exe")

    env = make(tmp_path, download=slow)
    env.updater.check()
    return env, started, release


def test_install_busy(tmp_path):
    env, started, release = blocking_env(tmp_path)
    t = threading.Thread(target=env.updater.install, args=(env.on_exit,))
    t.start()
    assert started.wait(5)
    try:
        with pytest.raises(UpdateBusy):
            env.updater.install(env.on_exit)
    finally:
        release.set()
        t.join(5)
    assert env.exited == 1


def test_start_install_busy_is_synchronous(tmp_path):
    env, started, release = blocking_env(tmp_path)
    env.updater.start_install(env.on_exit)
    assert env.updater.view()["state"] == "downloading"
    assert started.wait(5)
    try:
        with pytest.raises(UpdateBusy):
            env.updater.start_install(env.on_exit)
    finally:
        release.set()
    for _ in range(100):
        if env.exited:
            break
        threading.Event().wait(0.05)
    assert env.exited == 1


def test_install_retry_after_failure(tmp_path):
    env = make(tmp_path, sha=sha_text(b"autre"))
    env.updater.check()
    env.updater.install(env.on_exit)
    assert env.updater.view()["state"] == "failed"
    env.sha = sha_text(b"exe")
    env.updater.install(env.on_exit)
    assert env.updater.view()["state"] == "installing" and env.exited == 1
    assert env.updater.view()["error"] is None


def test_progress_reported(tmp_path):
    seen = []

    def dl(url, dest, progress):
        progress(50)
        seen.append(env.updater.view()["progress"])
        progress(100)
        seen.append(env.updater.view()["progress"])
        dest.write_bytes(b"exe")

    env = make(tmp_path, download=dl)
    env.updater.check()
    env.updater.install(env.on_exit)
    assert seen == [50, 100]


def test_install_unexpected_error_fails_and_allows_retry(tmp_path):
    calls = []

    def boom(url, dest, progress):
        dest.write_bytes(b"partiel")
        if not calls:
            calls.append(1)
            raise RuntimeError("imprévu")
        dest.write_bytes(b"exe")

    env = make(tmp_path, download=boom)
    env.updater.check()
    env.updater.install(env.on_exit)
    v = env.updater.view()
    assert v["state"] == "failed" and v["error"] and env.exited == 0
    assert not (tmp_path / "tmp" / "CoachCloclo-Setup-0.3.0.exe").exists()
    env.updater.install(env.on_exit)
    assert env.updater.view()["state"] == "installing" and env.exited == 1


def test_install_sha_with_bom(tmp_path):
    env = make(tmp_path, sha="﻿" + sha_text(b"exe"))
    env.updater.check()
    env.updater.install(env.on_exit)
    assert env.exited == 1


def test_install_on_exit_error_is_logged(tmp_path):
    env = make(tmp_path)
    env.updater.check()

    def bad():
        raise RuntimeError("zut")

    env.updater.install(bad)
    assert env.updater.view()["state"] == "installing"


def test_spawn_resets_pyinstaller_environment(monkeypatch):
    from coach.desktop import updater as module

    appels = []
    monkeypatch.setattr(module.subprocess, "Popen", lambda args, **kw: appels.append(kw))
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "C:/ancien")
    module._spawn(["setup.exe"])
    env = appels[0]["env"]
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert env["_PYI_APPLICATION_HOME_DIR"] == "C:/ancien"  # le reste de l'environnement est transmis
