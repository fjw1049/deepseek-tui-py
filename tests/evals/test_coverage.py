from evals.coverage import corpus_coverage
from evals.runner import load_cases
from evals.schema import EvalCase


def test_variants_and_probes_do_not_inflate_independent_task_coverage():
    base = EvalCase(id="a", suite="x", runner="product_session", grader="rubric",
                    source_group="one-origin", task_family="research")
    cases = [base, base.model_copy(update={"id": "b"}),
             base.model_copy(update={"id": "probe", "runner": "live_decision"}),
             base.model_copy(update={"id": "unknown", "source_group": ""})]
    coverage = corpus_coverage(cases)
    assert coverage["end_to_end_tasks"] == 3
    assert coverage["declared_sources"] == 1
    assert coverage["holdout_sources"] == 0
    assert coverage["missing_metadata"] == ["unknown"]


def test_personal_history_has_traceable_development_origins():
    cases = [c for c in load_cases() if c.suite == "personal_sessions"]
    coverage = corpus_coverage(cases)
    assert coverage["declared_sources"] == 10
    assert coverage["missing_metadata"] == []
    assert coverage["holdout_sources"] == 0
    for case in cases:
        assert case.source_group.split("-")[-1] in case.description


def test_campaign_check_is_read_only_and_never_starts_workers(monkeypatch, capsys):
    import json

    from evals.__main__ import main

    def forbidden(*args, **kwargs):
        raise AssertionError("check must not start a campaign")

    monkeypatch.setattr("evals.campaign.run_campaign", forbidden)
    assert main(["campaign", "evals/campaigns/offline-smoke.json", "--check"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["trials"] > 0
    assert report["coverage"]["end_to_end_tasks"] == 0
