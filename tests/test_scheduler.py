from __future__ import annotations

from opencode_talk_bridge.scheduler import Scheduler, TaskStore


def test_add_list_delete(tmp_path):
    store = TaskStore(str(tmp_path / "t.sqlite3"))
    tid = store.add("tok", "do X", run_at=100, interval_s=0, now=0)
    tasks = store.list("tok")
    assert len(tasks) == 1
    assert tasks[0].prompt == "do X"
    assert store.count() == 1
    store.delete(tid)
    assert store.list("tok") == []
    store.close()


def test_persistence(tmp_path):
    path = str(tmp_path / "t.sqlite3")
    store = TaskStore(path)
    store.add("tok", "later", run_at=500, now=0)
    store.close()
    reopened = TaskStore(path)
    assert reopened.list("tok")[0].prompt == "later"
    reopened.close()


def test_due_filters_by_time(tmp_path):
    store = TaskStore(str(tmp_path / "t.sqlite3"))
    store.add("tok", "soon", run_at=100, now=0)
    store.add("tok", "later", run_at=1000, now=0)
    due = store.due(now=200)
    assert [t.prompt for t in due] == ["soon"]
    store.close()


def test_one_shot_runs_once_then_deleted(tmp_path):
    store = TaskStore(str(tmp_path / "t.sqlite3"))
    store.add("tok", "boom", run_at=50, interval_s=0, now=0)
    fired = []
    sched = Scheduler(store, lambda token, prompt: fired.append((token, prompt)), clock=lambda: 100)
    sched.run_due()
    assert fired == [("tok", "boom")]
    assert store.count() == 0  # one-shot deleted
    store.close()


def test_recurring_reschedules(tmp_path):
    store = TaskStore(str(tmp_path / "t.sqlite3"))
    store.add("tok", "ping", run_at=50, interval_s=60, now=0)
    fired = []
    sched = Scheduler(store, lambda token, prompt: fired.append(prompt), clock=lambda: 100)
    sched.run_due()
    assert fired == ["ping"]
    assert store.count() == 1  # still there
    assert store.list("tok")[0].run_at == 160  # 100 + 60
    store.close()


def test_failing_task_does_not_break_loop(tmp_path):
    store = TaskStore(str(tmp_path / "t.sqlite3"))
    store.add("tok", "a", run_at=10, now=0)
    store.add("tok", "b", run_at=10, now=0)

    def runner(token, prompt):
        if prompt == "a":
            raise RuntimeError("boom")

    sched = Scheduler(store, runner, clock=lambda: 100)
    sched.run_due()  # must not raise
    assert store.count() == 0  # both consumed
    store.close()
