"""The model learns what the machine can run without probing it through tool calls."""

import json
import time

import pytest

from deepseek_tui.engine import capabilities as caps
from deepseek_tui.engine.capabilities import machine_capabilities, probe, render_capabilities
from deepseek_tui.engine.prompts import render_environment_block

FULL = {"python": "3.12.1", "node": "v22.0.0", "soffice": True, "pandoc": True,
        "timeout": "timeout", "gnu_sed": True, "office_python": None, "chrome": "/bin/chrome",
        "libraries": {"python-docx": True, "openpyxl": True, "python-pptx": True}}


@pytest.fixture
def fresh(monkeypatch):
    machine_capabilities.cache_clear()
    yield monkeypatch
    machine_capabilities.cache_clear()


def test_probe_reads_the_real_machine():
    found = probe()
    assert set(found) == set(FULL)
    assert found["python"]
    assert set(found["libraries"]) == set(FULL["libraries"])


def test_rendered_block_names_what_is_missing():
    text = render_capabilities({
        **FULL, "soffice": False, "timeout": None, "gnu_sed": False,
        "libraries": {"python-docx": True, "openpyxl": False, "python-pptx": False},
    })
    assert "has python-docx; no openpyxl, python-pptx" in text
    assert "soffice: not installed" in text
    assert "timeout command: none; prefer exec_shell timeout_ms" in text
    assert "BSD" in text


def test_app_interpreter_is_offered_for_document_scripts():
    text = render_capabilities({**FULL, "office_python": "/app/.venv/bin/python"})
    assert "office python: /app/.venv/bin/python" in text
    assert "load skill office-documents" in text
    assert "python-docx" in text
    assert "office python" not in render_capabilities(FULL)


def test_office_python_needs_every_library(monkeypatch):
    seen = {"docx", "openpyxl", "pptx"}
    monkeypatch.setattr(caps.importlib.util, "find_spec", lambda name: name in seen or None)
    assert probe()["office_python"]
    seen.discard("pptx")
    assert probe()["office_python"] is None


def test_gnu_machine_needs_no_timeout_note():
    assert "timeout command" not in render_capabilities(FULL)


def test_missing_interpreter_is_said_plainly():
    assert "- python: not installed" in render_capabilities({**FULL, "python": None})


def test_failed_probe_leaves_the_block_out():
    assert render_capabilities({}) == ""


def test_probing_happens_once_per_machine(fresh):
    calls = []
    fresh.setattr(caps, "probe", lambda: calls.append(1) or FULL)
    assert machine_capabilities() == FULL
    machine_capabilities.cache_clear()
    assert machine_capabilities() == FULL  # a new process reads the file
    assert len(calls) == 1


def test_a_stale_or_foreign_cache_is_probed_again(fresh):
    calls = []
    fresh.setattr(caps, "probe", lambda: calls.append(1) or FULL)
    machine_capabilities()
    path = caps._cache_path()
    saved = json.loads(path.read_text())
    path.write_text(json.dumps({**saved, "probed_at": time.time() - 2 * caps.CACHE_MAX_AGE_SECONDS}))
    machine_capabilities.cache_clear()
    machine_capabilities()
    path.write_text(json.dumps({**saved, "key": "another machine"}))
    machine_capabilities.cache_clear()
    machine_capabilities()
    assert len(calls) == 3


def test_corrupt_cache_is_not_a_failure(fresh):
    fresh.setattr(caps, "probe", lambda: FULL)
    caps._cache_path().parent.mkdir(parents=True, exist_ok=True)
    caps._cache_path().write_text("{not json")
    assert machine_capabilities() == FULL


def test_probe_failure_does_not_stop_startup(fresh):
    def boom():
        raise OSError("no fork")

    fresh.setattr(caps, "probe", boom)
    assert machine_capabilities() == {}


def test_block_stays_the_same_within_a_process(tmp_path, fresh):
    # It sits in the prefix the provider caches.
    seen = iter([FULL, {**FULL, "node": None}])
    fresh.setattr(caps, "probe", lambda: next(seen))
    assert render_environment_block(tmp_path) == render_environment_block(tmp_path)


def test_office_skill_ships_with_the_package():
    from deepseek_tui.integrations.skills import bundled_skills_dir

    text = (bundled_skills_dir() / "office-documents" / "SKILL.md").read_text()
    assert text.startswith("---\nname: office-documents\n")
    assert "office python" in text and "does not calculate" in text
