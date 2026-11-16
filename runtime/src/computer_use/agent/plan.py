"""A request's plan: the steps the main agent means to carry out for the user's message, as the whole list it last
wrote, and which of them are done. The next message starts without one. It holds no tasks: what runs is given when the
plan is shown, so a step and the task on it can be written in either order."""

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
        self.version = 0  # of the latest snapshot: a session's logs hold them, and the newest is the highest

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
        """In progress once a task is on it and the steps it needs are done: one task handed several steps in order
        works on the first that is open. A step the plan no longer has holds nothing."""
        known = {each.id for each in self.steps}
        ready = all(need in self.done for need in step.needs if need in known)
        status = "completed" if step.id in self.done else "in_progress" if tasks and ready else "pending"
        return {"id": step.id, "title": step.title, "done_when": step.done_when, "needs": list(step.needs),
                "status": status, "tasks": list(tasks)}
