# Bug fix

Every line you ship traces to evidence. A change that "might help" is a hypothesis; it does not ship.

1. Reproduce it on the surface where it was seen. For a run that went wrong, read its record first
   (`uv run --project clients/cli computer-use export RUN DIR`, or the run's folder under `runtime/data`) instead of
   theorizing. For the web page, drive the `web` dev server in the Browser pane. If it will not reproduce, narrow the
   conditions or add logging until it does.
2. Find the first place it went wrong. List the hypotheses, take the split that rules out the most, get evidence,
   repeat. Confirm the mechanism with evidence before planning a fix.
3. Write the failing test when there is a cheap unit path: `runtime/tests/unit` (fake model and screen in
   `conftest.py`), `clients/cli/tests` (fake API), or a Vitest file beside the web module. Keep its failing output.
4. Fix it at the root, with the smallest change. A guard is a fix only when the state it handles is legitimate. List
   what the fix lets you delete.
5. `scripts/check`, then repeat step 1's reproduction: it must pass on the same surface.

**Reply:** what was broken, the root cause, the fix, and the failing then passing output, verbatim.
