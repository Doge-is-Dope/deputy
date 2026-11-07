# Investigation

Read-only. The deliverable is a cited answer or a recommendation, not a code change.

1. Read the area's README layout table, then the code. Follow the data: where it is made, stored, sent and shown.
2. For "why is it like this", read `git log -S<name>` and `git log --follow <file>` before guessing.
3. For "how do others do it", read the vendors' code or docs (OpenAI, Anthropic, LangChain, xAI) and cite each.
4. When the answer is a fact you can observe (a timing, an output, a behaviour), run it rather than reason about it.
5. Write the answer: how it works, where it lives (`file:line`), gotchas. For a decision, a table of the options, doing
   nothing and removing something included, with their costs and your recommendation.

If the investigation turns into a change, say so and switch to [Bug fix](bug-fix.md) or [Feature](feature.md).

**Reply:** the answer, with a `file:line` or a command's output behind each claim. Push back if the premise is wrong.
