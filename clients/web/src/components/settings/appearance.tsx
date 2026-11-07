import { useState } from "react"
import { Radio } from "@base-ui/react/radio"
import { RadioGroup } from "@base-ui/react/radio-group"

import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  presetsFor,
  seedStyle,
  setColor,
  setMode,
  setTheme,
  useAppearance,
  type ColorRole,
  type Mode,
  type Seed,
  type Variant,
} from "@/lib/appearance"
import { PRESETS } from "@/lib/themes"
import { useT } from "@/lib/i18n"
import { Card, Row, Section } from "@/components/settings/layout"

const MODES: Mode[] = ["system", "light", "dark"]

/** The app in a mode and theme, in miniature: a message in the theme's accent, its reply, and the composer. Drawn in
    their own colors, whatever the page is in (index.css works them out again for a subtree with its own). */
function Miniature({ mode, seed }: { mode: Variant; seed: Seed }) {
  return (
    <g data-mode={mode} style={seedStyle(seed)}>
      <rect width="84" height="60" className="fill-background" />
      <rect
        x="50"
        y="11"
        width="24"
        height="3"
        rx="1.5"
        className="fill-link"
      />
      <rect
        x="10"
        y="21"
        width="44"
        height="3"
        rx="1.5"
        className="fill-muted-foreground/40"
      />
      <rect
        x="10"
        y="28"
        width="30"
        height="3"
        rx="1.5"
        className="fill-muted-foreground/40"
      />
      <rect
        x="9.5"
        y="42.5"
        width="65"
        height="10"
        rx="5"
        className="fill-card stroke-border"
      />
      <circle cx="69.5" cy="47.5" r="2.5" className="fill-link" />
    </g>
  )
}

/** A mode in the themes chosen for it. */
function ModePicture({
  mode,
  themes,
}: {
  mode: Mode
  themes: Record<Variant, Seed>
}) {
  return (
    <svg
      viewBox="0 0 84 60"
      aria-hidden
      className="block aspect-7/5 w-full sm:w-21"
    >
      {mode === "system" ? (
        <>
          <Miniature mode="light" seed={themes.light} />
          <svg x="42" width="42" height="60" viewBox="42 0 42 60">
            <Miniature mode="dark" seed={themes.dark} />
          </svg>
        </>
      ) : (
        <Miniature mode={mode} seed={themes[mode]} />
      )}
    </svg>
  )
}

/** A theme by name, beside an "Aa" in its accent on its background. */
function ThemeName({
  id,
  seed,
  mode,
}: {
  id: string
  seed: Seed
  mode: Variant
}) {
  const t = useT()
  return (
    <>
      <span
        aria-hidden
        data-mode={mode}
        style={seedStyle(seed)}
        className="flex size-5 items-center justify-center rounded-[5px] bg-background text-[0.625rem] font-semibold text-link ring-1 ring-foreground/15"
      >
        Aa
      </span>
      {PRESETS.find((preset) => preset.id === id)?.name ??
        t.settings.defaultTheme}
    </>
  )
}

/** Light or dark, then the theme of the mode the page is in: a theme from the list, and its three colors one by
    one. */
export function Appearance() {
  const t = useT()
  const { mode, resolved, themes } = useAppearance()
  const choice = themes[resolved]
  const presets = presetsFor(resolved)
  const colors: { role: ColorRole; label: string }[] = [
    { role: "accent", label: t.settings.accent },
    { role: "surface", label: t.settings.background },
    { role: "ink", label: t.settings.foreground },
  ]
  return (
    <Section>
      <Card>
        {/* The picture chosen is ringed, and each is named on hover. */}
        <Row label={t.settings.mode}>
          <RadioGroup
            aria-label={t.settings.mode}
            value={mode}
            onValueChange={(value) => setMode(value as Mode)}
            className="grid grid-cols-3 gap-2 sm:flex sm:gap-3"
          >
            {MODES.map((value) => (
              <Tooltip key={value}>
                <TooltipTrigger
                  render={
                    <Radio.Root
                      value={value}
                      aria-label={t.settings.modes[value]}
                      className="rounded-[11px] p-[3px] ring-2 ring-transparent transition-[box-shadow,scale] duration-150 ease-(--ease-out) outline-none not-data-checked:hover:ring-foreground/15 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring active:scale-[0.97] data-checked:ring-link"
                    />
                  }
                >
                  <span className="block overflow-hidden rounded-lg ring-1 ring-foreground/10">
                    <ModePicture mode={value} themes={themes} />
                  </span>
                </TooltipTrigger>
                <TooltipContent>{t.settings.modes[value]}</TooltipContent>
              </Tooltip>
            ))}
          </RadioGroup>
        </Row>
      </Card>
      <Card>
        <Row label={t.settings.theme}>
          <Select
            value={choice.id}
            onValueChange={(id) => {
              const preset = presets.find((each) => each.id === id)
              if (preset) setTheme(resolved, preset)
            }}
          >
            <SelectTrigger aria-label={t.settings.theme}>
              <SelectValue>
                {(id: string) => (
                  <ThemeName id={id} seed={choice} mode={resolved} />
                )}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {presets.map((preset) => (
                <SelectItem key={preset.id} value={preset.id}>
                  <ThemeName
                    id={preset.id}
                    seed={preset[resolved]!}
                    mode={resolved}
                  />
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Row>
        {colors.map(({ role, label }) => (
          <Row key={role} label={label}>
            <ColorField
              label={label}
              value={choice[role]}
              onChange={(color) => setColor(resolved, role, color)}
            />
          </Row>
        ))}
      </Card>
    </Section>
  )
}

/** A color as a swatch and its hex code: the swatch opens the system's color picker, and
    the code can be typed, taking effect once it is six digits. */
function ColorField({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (color: string) => void
}) {
  const [draft, setDraft] = useState<string | null>(null)
  return (
    <div className="relative w-30">
      <span
        className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 rounded-full ring-1 ring-foreground/15"
        style={{ backgroundColor: value }}
      >
        <input
          type="color"
          aria-label={label}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="absolute inset-0 size-full cursor-pointer opacity-0"
        />
      </span>
      <Input
        aria-label={label}
        spellCheck={false}
        value={(draft ?? value).toUpperCase()}
        onChange={(event) => {
          const digits = event.target.value
            .toUpperCase()
            .replace(/[^0-9A-F]/g, "")
            .slice(0, 6)
          const typed = `#${digits}`
          if (digits.length === 6) {
            setDraft(null)
            onChange(typed)
          } else setDraft(typed)
        }}
        onBlur={() => setDraft(null)}
        className="h-9 pl-9 text-foreground tabular-nums"
      />
    </div>
  )
}
