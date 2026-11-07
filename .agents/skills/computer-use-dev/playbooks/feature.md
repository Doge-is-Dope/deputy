# Feature

1. Read the area's README and the code it touches. For agent loop, prompt or runtime behaviour changes,
   check the relevant major products as described in SKILL.md.
2. Name the data shape and where it lives. Runtime state belongs to a run or a conversation; user choices live in
   the client and are sent per run. A new event or field follows the event record's path (SKILL.md, Rules).
3. Subtract first: can an existing setting, component, event or tool be generalised or removed to cover this? List
   what the feature lets you delete. Build only the cases that occur now, through the area's existing entry point
   (SKILL.md, "Smaller, never harder to read"); a new entry point only when none fits, and named for what it is.
4. For UI, show rendered mockups (desktop and phone width) before building when the visual direction is
   undecided, and get that direction approved.
   Existing approval or a supplied design is sufficient within its scope. Use only patterns
   the reference products have (the `design-system` skill lists them, with its type scale and icon rules).
5. Build it in small units that each end in a passing check. Tests assert what a user of the code observes.
6. `scripts/check`, then see it on the real surface (SKILL.md, table). For motion or layout, capture a
   screenshot or
   a recording as proof.
7. Update the README that describes the area so it describes the code as it now is.

**Reply:** what it does for the user, the data shape you chose and why, the alternatives in a table when there were
real ones, and open decisions.
