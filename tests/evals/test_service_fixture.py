from evals.harness.service_fixture import terminal_checks


def passed(kind, state, answers):
    return all(row["passed"] for row in terminal_checks(kind, state, answers))


def test_login_needs_both_views_and_current_code():
    state = {"visits": [False, True], "value": "secret"}
    assert passed("login", state, ["请登录", "secret"])
    assert not passed("login", state, ["secret", "旧码"])
    assert not passed("login", {**state, "visits": [True]}, ["secret"])


def test_correct_receipt_does_not_excuse_duplicate_enqueue():
    state = {"receipts": 1, "writes": ["monthly"], "value": "r1"}
    assert passed("retry", state, ["r1"])
    assert not passed("retry", {**state, "writes": ["monthly"] * 2}, ["r1"])
    assert not passed("retry", {**state, "receipts": 0}, ["r1"])


def test_same_id_in_wrong_partition_fails_even_if_corrected():
    target = ["/tickets/west/17", "v"]
    state = {"writes": [target], "value": "v"}
    assert passed("transfer", state, [])
    assert not passed("transfer", {**state, "writes": [["/tickets/east/17", "v"], target]}, [])
