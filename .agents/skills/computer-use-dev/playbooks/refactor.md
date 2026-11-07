# Refactor

Behaviour stays the same; the code gets smaller or easier to follow.

1. Say what the reader gains: fewer layers between a question and its answer, less hidden state, one rule
   instead of
   several patches.
2. Remove first: dead code, one-caller wrappers, injected factories with one implementation, modules holding one
   dataclass. Keep seams that name a real boundary (the ports `adapters.py` wires: computer, code runner, stores).
   Stop where a cut would cost readability: a named idea stays named, and things that change for different reasons
   stay apart.
3. Migrate every caller and delete the old API in the same change. No compatibility layer.
4. Tests that pass before must pass after unchanged. If a test needs changing, determine whether the public
   contract changed or the test was coupled to
   implementation details. Keep behavioural assertions; explain any necessary test changes.
5. `scripts/check --all` when the change crosses areas, else `scripts/check`.

**Reply:** what moved or went away (lines before and after), and the checks that show behaviour held.
