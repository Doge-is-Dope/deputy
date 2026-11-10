"""A conversation's plan: the steps the main agent means to carry out, as the whole list it last wrote, and which of
them are done. It holds no tasks: what runs is given when the plan is shown, so a step and the task on it can be
written in either order."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from computer_use.events import PlanSnapshot, PlanStep
from computer_use.prompts import notes

MAX_STEPS = 12


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    done_when: str = ""  # how to tell it is done
    needs: tuple[str, ...] = ()  # the steps it follows, for whoever reads the plan: nothing holds a step back for them


class PlanError(ValueError):
    """A plan that cannot be written, in the main agent's words."""


class Plan:
    def __init__(self):
        self.steps: tuple[Step, ...] = ()
        self.done: set[str] = set()  # the ids of the steps that are done
        self.version = 0  # of the latest snapshot: logs of several turns hold them, and the newest is the highest

    @classmethod
    def restored(cls, snapshot: PlanSnapshot) -> "Plan":
        """The plan a snapshot showed. Nothing runs in a new session, so a step in progress then is not done now."""
        plan = cls()
        plan.steps = tuple(Step(s["id"], s["title"], s["done_when"], tuple(s["needs"])) for s in snapshot["steps"])
        plan.done = {s["id"] for s in snapshot["steps"] if s["status"] == "completed"}
        plan.version = snapshot["version"]
        return plan

    def write(self, steps: Sequence[Step], finished: Iterable[str] = (), reopened: Iterable[str] = ()) -> None:
        """Replace the list. A step that stays keeps whether it is done, unless named in `finished` or `reopened`."""
        ids = {step.id for step in steps}
        if not 1 <= len(steps) <= MAX_STEPS or len(ids) != len(steps) or not all(s.id and s.title for s in steps):
            raise PlanError(notes.bad_plan(MAX_STEPS))
        self.steps = tuple(steps)
        self.done = ((self.done | set(finished)) - set(reopened)) & ids

    def finish(self, ids: Sequence[str]) -> list[str]:
        """Mark steps done; those of `ids` the plan does not have, which change nothing."""
        known = {step.id for step in self.steps}
        self.done |= set(ids) & known
        return [id for id in ids if id not in known]

    def snapshot(self, running: Mapping[str, Sequence[str]]) -> PlanSnapshot:
        """The plan as it stands, each step with the tasks at work on it (`running`: task ids by step id), under a
        version of its own."""
        self.version += 1
        return {"version": self.version, "steps": self.view(running)}

    def view(self, running: Mapping[str, Sequence[str]]) -> list[PlanStep]:
        """The steps as they stand, each with the tasks at work on it."""
        return [self._shown(step, running.get(step.id, ())) for step in self.steps]

    def _shown(self, step: Step, tasks: Sequence[str]) -> PlanStep:
        status = "completed" if step.id in self.done else "in_progress" if tasks else "pending"
        return {"id": step.id, "title": step.title, "done_when": step.done_when, "needs": list(step.needs),
                "status": status, "tasks": list(tasks)}
