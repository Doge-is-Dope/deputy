# Prompt or model change

Prompts live in `runtime/src/computer_use/prompts/`. The eval versions them apart from the code and shows their diff
when only prompts differ between two versions.

1. Write down the general computer-use behaviour you want to change. A rule that only fixes one eval task does not ship;
   record the finding instead.
2. Read how OpenAI's and Anthropic's computer-use guides and reference prompts handle it, and cite them.
3. Remove or reword an existing rule before adding one: a prompt that grows with each finding overfits. Make the
   smallest wording change, and keep provider-specific behaviour out of shared prompts.
4. Plan the A/B: which tasks exercise the behaviour, 3+ trials each, and the baseline (existing results for the base
   version under `eval/results/`, or `--version HEAD`). Ask the user before running: runs change the Windows machine
   and spend API money.
5. Before each batch, `uv run --project clients/cli computer-use status --idle`, and a clean desktop
   (`eval/ev reset`). Run with `--note` so the report names the version; alternate base and change task by task.
   Model swaps use `--main` or `--computer` instead of a code change.
6. Grading is the user's: hand them `results/<version>/grade.md`, or, when asked, propose grades with what you saw in
   each run. Then `eval/ev report` and compare pass rates, endings, cost and p50/p95.

**Reply:** the change, the tasks and trials, pass rates and timings for both versions, and whether the difference is
larger than run-to-run noise.
