import sys

from coach.proc import NO_WINDOW, find_claude


def test_no_window_flag_matches_platform():
    assert (NO_WINDOW != 0) == (sys.platform == "win32")


def test_find_claude_prefers_path(tmp_path):
    assert find_claude(which=lambda n: "C:/bin/claude.exe", home=tmp_path) == "C:/bin/claude.exe"


def test_find_claude_falls_back_to_local_bin(tmp_path):
    name = "claude.exe" if sys.platform == "win32" else "claude"
    exe = tmp_path / ".local" / "bin" / name
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert find_claude(which=lambda n: None, home=tmp_path) == str(exe)


def test_find_claude_absent(tmp_path):
    assert find_claude(which=lambda n: None, home=tmp_path) is None
