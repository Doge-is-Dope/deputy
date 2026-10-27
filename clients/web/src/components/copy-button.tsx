import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useCopy } from "@/hooks/use-copy"
import { useT } from "@/lib/i18n"
import { CheckIcon, CopyIcon } from "@/components/icons"

/** Keep the tooltip open through copying so confirmation replaces its text without flicker. */
export function CopyButton({
  text,
  disabled = false,
}: {
  text: string
  disabled?: boolean // a code block still being written
}) {
  const t = useT()
  const { copied, copy } = useCopy()
  const label = copied ? t.common.copied : t.common.copy
  return (
    <Tooltip>
      <TooltipTrigger
        closeOnClick={false}
        render={
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={label}
            disabled={disabled}
            className="text-muted-foreground"
            onClick={() => copy(text)}
          />
        }
      >
        <span className="swap">
          <CheckIcon className="size-4" data-hidden={copied ? undefined : ""} />
          <CopyIcon className="size-4" data-hidden={copied ? "" : undefined} />
        </span>
      </TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  )
}
