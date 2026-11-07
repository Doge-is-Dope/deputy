# Perf

Tie every change to a measurement. Reading code is not measuring.

1. Take a baseline where the cost is paid:
   - Runtime CPU: in a container limited to `--cpus=0.25` (many runtimes will share one host), not natively.
   - Web: a production build (`bun run build && bun run preview`) traced in Chrome with 4x CPU throttling.
   - Task time: the eval's per-task p50/p95 (`eval/ev report`), 3+ trials, versions alternated task by task.
2. Find what limits it before changing anything: model calls (usually most of a task's time), CPU, the event loop,
   I/O, rendering. Then try, cheapest first: don't do it; don't do it again; do less; do it later; do it concurrently;
   do it cheaper. Stop at the first that meets the target.
3. One change at a time. Measure each; revert what did not help.
4. Check the number: repeat runs, the same conditions for both sides, no errors hidden in the faster run, and that the
   gain shows end to end, not only in a micro-benchmark.

Known traps here:

- Pillow filters hold the GIL. `asyncio.to_thread` around them still stalls the event loop; pick a cheaper operation.
- Work on raw images in hot loops; encode only the frame that goes to the model or to disk.
- The React Compiler does not memoize everything in `App`; count renders before assuming it does.
- An animation with fill-mode `both` keeps every finished element composited; long replies pile up layers.

**Reply:** baseline, after, delta, how and where it was measured, and the artifact paths.
