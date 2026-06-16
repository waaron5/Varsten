import { cn } from "@/lib/utils"

export function VarstenLogo({
  className,
  showWordmark = true,
}: {
  className?: string
  showWordmark?: boolean
}) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <span className="sr-only">Varsten</span>
      <svg
        viewBox="0 0 32 32"
        width="28"
        height="28"
        fill="none"
        aria-hidden="true"
        className="shrink-0"
      >
        <rect width="32" height="32" rx="7" className="fill-primary" />
        {/* downward "savings" chevron mark */}
        <path
          d="M8 10.5L16 22L24 10.5"
          stroke="var(--color-accent)"
          strokeWidth="2.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M8 16.5L16 22"
          stroke="var(--color-primary-foreground)"
          strokeWidth="2.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity="0.45"
        />
      </svg>
      {showWordmark && (
        <span className="text-[1.15rem] font-semibold tracking-tight text-foreground">
          Varsten
        </span>
      )}
    </span>
  )
}
