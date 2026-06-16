import type { AnchorHTMLAttributes } from "react"
import { cn } from "@/lib/utils"

type Variant = "primary" | "outline" | "accent" | "ghost" | "outline-invert"

const base =
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-lg text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background [&_svg]:h-4 [&_svg]:w-4 [&_svg]:shrink-0"

const sizes = {
  default: "h-10 px-4",
  lg: "h-12 px-6 text-[0.95rem]",
}

const variants: Record<Variant, string> = {
  primary: "bg-primary text-primary-foreground hover:bg-primary/90",
  accent: "bg-accent text-accent-foreground hover:bg-accent/90",
  outline: "border border-border bg-card text-foreground hover:bg-secondary",
  ghost: "text-foreground hover:bg-secondary",
  "outline-invert":
    "border border-primary-foreground/20 bg-transparent text-primary-foreground hover:bg-primary-foreground/10",
}

export function ButtonLink({
  variant = "primary",
  size = "default",
  className,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement> & {
  variant?: Variant
  size?: keyof typeof sizes
}) {
  return (
    <a
      className={cn(base, sizes[size], variants[variant], className)}
      {...props}
    />
  )
}
