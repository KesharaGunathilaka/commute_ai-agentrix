"use client";

import { AlertTriangle, Bus, Gauge, Scale, Shuffle, Train, Zap } from "lucide-react";

import { ProvenanceBadge } from "@/components/journey/ProvenanceBadge";
import { Panel, PanelHeader } from "@/components/ui/primitives";
import type { PlanTotalFare, PlanVariant, ProvenanceSummary } from "@/lib/types";
import { cn, formatDuration } from "@/lib/utils";

const STRATEGY_ICONS = {
  fastest: Zap,
  cheapest: Scale,
  balanced: Gauge,
} as const;

/**
 * A filler card — one that occupies a slot freed when two strategies collapsed
 * onto the same route — wins no strategy, so `strategies` is empty. It gets a
 * neutral glyph rather than borrowing one that implies an advantage it does
 * not claim.
 */
function variantIcon(variant: PlanVariant) {
  const key = variant.strategies?.[0] as keyof typeof STRATEGY_ICONS | undefined;
  return (key && STRATEGY_ICONS[key]) || Shuffle;
}

const PROVENANCE_COPY: Record<ProvenanceSummary, string> = {
  verified: "Every leg from a checked source.",
  partially_verified: "Some legs unchecked.",
  estimated: "No leg checked against a published timetable.",
};

/**
 * The plan's total fare.
 *
 * An incomplete total leads with "at least" and says how many legs it covers.
 * The alternative — printing a sum that quietly omits an unpriced leg — reads
 * as a complete price and is wrong in the direction that costs the commuter
 * money, so the hedge is not optional decoration.
 */
function TotalFare({ fare }: { fare: PlanTotalFare }) {
  if (fare.amount == null) {
    return (
      <div className="mt-2.5 rounded-lg border border-console-700/60 bg-console-900/40 px-2.5 py-2">
        <p className="eyebrow">Total fare</p>
        <p className="mt-0.5 text-sm font-semibold text-ink-500">Not available</p>
        <p className="mt-1 text-[10px] text-ink-700">
          No leg on this plan could be priced. Unknown, not free.
        </p>
      </div>
    );
  }

  const currency = fare.currency ?? "LKR";
  const range =
    fare.max_amount != null && fare.max_amount > fare.amount
      ? `${currency} ${fare.amount.toLocaleString("en-LK")}–${fare.max_amount.toLocaleString("en-LK")}`
      : `${currency} ${fare.amount.toLocaleString("en-LK")}`;
  const margin = fare.uncertainty_pct ? `±${Math.round(fare.uncertainty_pct * 100)}%` : null;

  return (
    <div className="mt-2.5 rounded-lg border border-console-700/60 bg-console-900/40 px-2.5 py-2">
      <p className="eyebrow">Total fare{fare.complete ? "" : " (partial)"}</p>
      <p className="mt-0.5 text-sm font-semibold text-glow-400">
        {fare.complete ? "" : "at least "}
        <span className="tabular">{range}</span>
        {margin && <span className="ml-1 text-[10px] font-normal text-ink-500">{margin}</span>}
      </p>
      <p className="mt-1 text-[10px] leading-relaxed text-ink-700">
        {fare.complete
          ? `Sum of ${fare.total_legs} leg${fare.total_legs === 1 ? "" : "s"}. Widest leg margin applied.`
          : `Only ${fare.priced_legs} of ${fare.total_legs} legs could be priced — the rest is unknown, not free.`}
      </p>
    </div>
  );
}

function VariantCard({ variant }: { variant: PlanVariant }) {
  const Icon = variantIcon(variant);
  const ModeIcon = variant.transit_mode === "train" ? Train : Bus;

  return (
    <Panel className="flex flex-col p-3">
      <div className="flex items-start justify-between gap-2">
        <span className="flex items-center gap-1.5">
          <span className="grid size-6 shrink-0 place-items-center rounded-md bg-signal-500/10 text-signal-400">
            <Icon className="size-3" />
          </span>
          <span className="text-xs font-semibold text-ink-100">{variant.label}</span>
        </span>
        <ModeIcon className="size-3.5 shrink-0 text-ink-500" />
      </div>

      <p className="mt-1 text-[10px] text-ink-700">{variant.blurb}</p>

      <div className="tabular mt-2.5 flex items-baseline gap-1.5">
        <span className="text-sm font-semibold text-signal-400">
          {variant.departure_time || "—"}
        </span>
        <span className="text-ink-700">→</span>
        <span className="text-sm font-semibold text-ink-100">{variant.arrival_time || "—"}</span>
        <span className="ml-auto text-[11px] text-ink-500">
          {formatDuration(variant.total_duration_min ?? null)}
        </span>
      </div>

      {variant.missed_deadline && (
        <p className="mt-1.5 flex items-center gap-1 text-[10px] font-semibold text-alert-400">
          <AlertTriangle className="size-2.5 shrink-0" />
          Arrives after your deadline
        </p>
      )}

      <TotalFare fare={variant.total_fare} />

      {/* Attributed to where the *displayed times* came from, which is not
          always the legs' source: local timetable data can replace a route's
          headline departure and arrival while the per-leg times stay as Maps
          recorded them. Captioning those minutes "Google Maps" would credit a
          number to a source that didn't produce it. */}
      <div className="mt-2 flex flex-wrap items-center gap-1">
        <ProvenanceBadge
          provenance={{
            source: variant.times_source ?? variant.legs[0]?.source ?? null,
            verified: variant.provenance_summary === "verified",
          }}
          prefix="Times"
        />
      </div>
      <p className="mt-1 text-[10px] leading-relaxed text-ink-700">
        {PROVENANCE_COPY[variant.provenance_summary]}
        {variant.times_overridden && " Times replaced Google Maps'."}
      </p>
    </Panel>
  );
}

/**
 * Fastest, cheapest and balanced, side by side.
 *
 * Fewer than three cards is the normal case, not a bug: when two strategies
 * pick the same route they collapse into one card labelled for both. Three
 * identical cards under three headings would claim the agent found three
 * plans when it found one.
 *
 * Every figure here was computed by the ranker and the fare model. None of it
 * passed through a language model on the way to the screen.
 */
export function PlanVariants({
  variants,
  className,
}: {
  variants?: PlanVariant[] | null;
  className?: string;
}) {
  if (!variants || variants.length === 0) return null;

  return (
    <Panel className={cn("p-4", className)}>
      <PanelHeader
        icon={<Scale className="size-3.5" />}
        title={variants.length === 1 ? "One plan leads on every measure" : "Compare plans"}
        meta={
          <span className="text-[11px] text-ink-500">
            {variants.length} distinct option{variants.length === 1 ? "" : "s"}
          </span>
        }
      />

      <div
        className={cn(
          "mt-3 grid gap-2.5",
          variants.length >= 3 ? "sm:grid-cols-3" : variants.length === 2 ? "sm:grid-cols-2" : "",
        )}
      >
        {variants.map((variant) => (
          <VariantCard key={variant.variant_id} variant={variant} />
        ))}
      </div>
    </Panel>
  );
}
