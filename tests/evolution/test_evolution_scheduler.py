from deepseek_tui.post_turn.scheduler import PeriodicTurnScheduler


def test_evolution_memory_nudge_not_due_on_first_turn() -> None:
    sched = PeriodicTurnScheduler(every_n=10, warmup_enabled=False)
    sched.notify("thread-1", object())
    assert not sched.is_due("thread-1")


def test_evolution_memory_nudge_due_after_every_n() -> None:
    sched = PeriodicTurnScheduler(every_n=3, warmup_enabled=False)
    for _ in range(2):
        sched.notify("thread-1", object())
    assert not sched.is_due("thread-1")
    sched.notify("thread-1", object())
    assert sched.is_due("thread-1")
