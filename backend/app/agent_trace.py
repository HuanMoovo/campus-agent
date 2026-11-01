"""Small per-request execution record; never contains prompts, credentials or errors."""
from contextlib import contextmanager
from time import perf_counter
from uuid import uuid4


class RunTrace:
    def __init__(self):
        self.id = str(uuid4())
        self.started = perf_counter()
        self.steps: list[dict] = []
        self.task: dict | None = None

    @contextmanager
    def phase(self, name: str):
        started = perf_counter()
        step = {"phase": name, "status": "completed", "duration_ms": 0}
        self.steps.append(step)
        try:
            yield step
        except BaseException:
            step["status"] = "failed"
            raise
        finally:
            step["duration_ms"] = round(max(0, perf_counter() - started) * 1000)

    def snapshot(self, status: str = "completed") -> dict:
        if status == "completed" and self.task and self.task["stop_reason"] != "completed":
            all_attempts_failed = (self.task["attempted_steps"] > 0 and not self.task["completed_steps"]
                                   and any(step["phase"] == "tool" and step["status"] == "failed" for step in self.steps))
            status = "failed" if all_attempts_failed else "partial"
        if status == "completed" and any(step["status"] == "failed" for step in self.steps):
            status = "failed"
        return {"id": self.id, "status": status,
                "duration_ms": round(max(0, perf_counter() - self.started) * 1000),
                "steps": [dict(step) for step in self.steps],
                **({"task": dict(self.task)} if self.task is not None else {})}
