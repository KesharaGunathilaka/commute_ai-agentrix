import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

/* ── Button ─────────────────────────────────────────────────────────────── */

const button = cva(
  "inline-flex items-center justify-center gap-2 rounded-lg font-medium whitespace-nowrap transition " +
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal-500 " +
    "disabled:pointer-events-none disabled:opacity-45",
  {
    variants: {
      variant: {
        // Hover goes darker, not brighter: signal-400 is the deeper cyan on
        // this palette. A glow would read as emitted light, which only makes
        // sense against a dark ground — a lifted shadow is the light-theme
        // equivalent of the same "this is the primary action" cue.
        primary:
          "bg-signal-500 text-white hover:bg-signal-400 shadow-sm shadow-signal-600/25",
        subtle: "bg-console-800 text-ink-100 hover:bg-console-700 border border-console-700",
        ghost: "text-ink-300 hover:text-ink-100 hover:bg-console-800",
        danger: "bg-alert-500/15 text-alert-400 border border-alert-500/40 hover:bg-alert-500/25",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-10 px-4 text-sm",
        icon: "h-9 w-9 p-0",
      },
    },
    defaultVariants: { variant: "subtle", size: "md" },
  },
);

export function Button({
  className,
  variant,
  size,
  ...props
}: ComponentProps<"button"> & VariantProps<typeof button>) {
  return <button className={cn(button({ variant, size }), className)} {...props} />;
}

/* ── Badge ──────────────────────────────────────────────────────────────── */

const badge = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold",
  {
    variants: {
      tone: {
        neutral: "border-console-600 bg-console-800/70 text-ink-300",
        signal: "border-signal-500/40 bg-signal-500/10 text-signal-400",
        glow: "border-glow-400/40 bg-glow-400/10 text-glow-400",
        alert: "border-alert-500/40 bg-alert-500/10 text-alert-400",
        go: "border-go-500/35 bg-go-500/10 text-go-400",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Badge({
  className,
  tone,
  ...props
}: ComponentProps<"span"> & VariantProps<typeof badge>) {
  return <span className={cn(badge({ tone }), className)} {...props} />;
}

/* ── Panel ──────────────────────────────────────────────────────────────── */

export function Panel({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("panel", className)} {...props} />;
}

/** Section heading with the small uppercase eyebrow label. */
export function PanelHeader({
  icon,
  title,
  meta,
  className,
}: {
  icon?: ReactNode;
  title: string;
  meta?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center justify-between gap-3", className)}>
      <div className="flex items-center gap-2">
        {icon ? <span className="text-signal-500">{icon}</span> : null}
        <span className="eyebrow">{title}</span>
      </div>
      {meta}
    </div>
  );
}

/* ── Spinner ────────────────────────────────────────────────────────────── */

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cn(
        "inline-block size-4 animate-spin rounded-full border-2 border-current border-t-transparent",
        className,
      )}
    />
  );
}

/* ── Time ───────────────────────────────────────────────────────────────── */

/** A clock time in the departure-board treatment. */
export function TimeChip({
  value,
  tone = "default",
  className,
}: {
  value: string;
  tone?: "default" | "signal" | "muted";
  className?: string;
}) {
  return (
    <span
      className={cn(
        "tabular text-sm font-semibold",
        tone === "signal" && "text-signal-400",
        tone === "muted" && "text-ink-500",
        tone === "default" && "text-ink-100",
        className,
      )}
    >
      {value}
    </span>
  );
}
