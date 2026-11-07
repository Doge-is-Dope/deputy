# Ship

1. `scripts/check --base main` passes. CI also runs the dependency audits and a secret scan.
2. Read your own diff and cut what the change does not need: a helper with one caller, a setting, a fallback for a
   case that has not occurred. Then read it as a stranger: names say what things are, each function does one job, and
   the next similar case would be one more entry. No debug output, leftover files, personal or machine details;
   comments short.
3. Commit only when asked. One line, Angular style, about 70 characters: `fix(runtime): stop a run whose desktop
   dropped`. No body. Before committing, `git branch --show-current` and `git log --oneline main..HEAD`, so a peer's
   commit does not ride along; stage only your own files.
4. Merge only when asked: `git fetch`, check that `origin/main` is an ancestor of the branch, then
   `git checkout main && git merge --ff-only <branch> && git push origin main`. If it cannot fast-forward, stop and
   ask before rebasing.
5. The container runs a copy of main and never follows edits. After a merge that touches `runtime/` or `code-runner/`,
   with the user's agreement:
   `uv run --project clients/cli computer-use status --idle && (cd runtime && docker compose up -d --build)`.
   If it is busy, say so and leave the rebuild for later.
6. Delete a merged branch only when asked, with `git branch -d`, never `-D`.

**Reply:** what landed (commits, branch), the checks that ran, and whether the container was rebuilt.
