import { useId, type SVGProps } from "react"

/** Two soft colours and the direction between them, from the user's id: the same each time they come, nothing kept. */
function gradientOf(id: string) {
  let hash = 2166136261 // FNV-1a, which spreads even short ids such as "local" across the wheel
  for (const char of id) hash = Math.imul(hash ^ char.codePointAt(0)!, 16777619)
  hash >>>= 0
  const hue = hash % 360
  return {
    from: `hsl(${hue} 45% 84%)`,
    to: `hsl(${(hue + 40 + ((hash >>> 9) % 60)) % 360} 40% 72%)`,
    angle: (hash >>> 17) % 360,
  }
}

/** The user's circle at the foot of the sidebar: a pale gradient of their own, between two colours of their id. */
export function UserAvatar({
  id,
  ...props
}: { id: string } & SVGProps<SVGSVGElement>) {
  const gradient = useId()
  const { from, to, angle } = gradientOf(id)
  return (
    <svg viewBox="0 0 20 20" aria-hidden {...props}>
      <defs>
        <linearGradient
          id={gradient}
          gradientTransform={`rotate(${angle} .5 .5)`}
        >
          <stop offset="0" stopColor={from} />
          <stop offset="1" stopColor={to} />
        </linearGradient>
      </defs>
      <circle cx="10" cy="10" r="10" fill={`url(#${gradient})`} />
    </svg>
  )
}
