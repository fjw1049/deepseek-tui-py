import httpx
import pytest

from evals.harness.service_fixture import service_fixture, terminal_checks


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


@pytest.mark.parametrize("kind", ["retry", "retry_uncommitted"])
def test_timeout_pair_requires_observing_state_before_recovery(kind):
    with service_fixture(kind) as (state, urls), httpx.Client(trust_env=False) as client:
        url = urls["source"] + "/jobs/monthly"
        assert client.post(url).status_code == 504
        answer = client.get(url).text
        if kind == "retry_uncommitted":
            assert answer == "尚未入队"
            assert not passed(kind, state, [answer])  # Giving up must fail.
            response = client.post(url)
            assert response.status_code == 200
            answer = response.text  # A successful response already contains a valid receipt.
        assert passed(kind, state, [answer])
        client.post(url)
        assert not passed(kind, state, [answer])  # A duplicate must fail in either condition.


def test_blind_retry_is_not_a_verified_recovery():
    with (
        service_fixture("retry_uncommitted") as (state, urls),
        httpx.Client(trust_env=False) as client,
    ):
        url = urls["source"] + "/jobs/monthly"
        client.post(url)
        client.post(url)
        answer = client.get(url).text
        assert not passed("retry_uncommitted", state, [answer])
