from deepseek_tui.post_turn.scheduler import PeriodicTurnScheduler


def test_scheduler_every_n_and_reset() -> None:
    sched = PeriodicTurnScheduler(every_n=3, warmup_enabled=False)
    sched.notify("t1", "a")
    assert not sched.is_due("t1")
    sched.notify("t1", "b")
    assert not sched.is_due("t1")
    sched.notify("t1", "c")
    assert sched.is_due("t1")
    sched.reset("t1")
    assert not sched.is_due("t1")
    assert sched.count("t1") == 0
