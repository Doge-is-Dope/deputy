import { useNow } from "@/hooks/use-now"
import { useTook } from "@/hooks/use-took"
import { useWorked } from "@/hooks/use-worked"
import { awaitingDesktop, waitingFor, workedFor, type Task } from "@/lib/thread"

/**
 * A task's clock, as the conversation's work group and the live view both show it: since when the user has had the
 * desktop it uses (`took`, by the status or its log), and how long it has worked (`worked`), leaving out the time it
 * waited for the user. It ticks while the task is `running`; one that never ended stops at the run's `last` event.
 */
export function useTaskClock(
  task: Task | null,
  userSince: number | null,
  running: boolean,
  last: number | null = null
) {
  const took = useTook(userSince, task !== null && awaitingDesktop(task))
  const now = useNow(running)
  const until = task?.ended ?? (running ? now : (last ?? task?.started ?? now))
  const worked = useWorked(
    task ? workedFor(task, until, running ? waitingFor(task, took) : null) : 0,
    task?.key ?? ""
  )
  return { took, worked }
}
