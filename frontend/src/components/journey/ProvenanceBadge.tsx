"use client";

import { ShieldCheck, ShieldQuestion } from "lucide-react";

import type { Provenance, Route } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Human names for the source ids the backend stamps.
 *
 * An unknown id falls through to the raw string rather than a placeholder:
 * if a new source appears, showing its id is more useful than hiding it.
 */
const SOURCE_LABELS: Record<string, string> = {
  google_maps: "Google Maps",
  local_timetable: "Local timetable",
  sri_lanka_railways: "Sri Lanka Railways",
  ntc: "NTC",
  simulated: "Simulated",
  fare_model: "Fare model",
};

export function sourceLabel(source?: string | null): string {
  if (!source) return "source unrecorded";
  return SOURCE_LABELS[source] ?? source.replace(/_/g, " ");
}

/**
 * "Bus · estimated · Google Maps" — one line of attribution.
 *
 * Deliberately shows "estimated" rather than nothing when a source is
 * unverified. A badge that only appears on verified data would make the
 * absence of a badge mean two different things (unverified, or a client too
 * old to render it), and the whole point is that the commuter can tell which
 * numbers have been checked.
 */
export function ProvenanceBadge({
  provenance,
  prefix,
  className,
}: {
  provenance?: Provenance | null;
  /** Leading term, e.g. the mode: "Train", "Bus". */
  prefix?: string;
  className?: string;
}) {
  const verified = provenance?.verified === true;
  const Icon = verified ? ShieldCheck : ShieldQuestion;

  const parts = [
    prefix,
    verified ? "verified" : "estimated",
    sourceLabel(provenance?.source),
    provenance?.captured_date ? `captured ${provenance.captured_date}` : null,
  ].filter(Boolean);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded border px-1.5 py-px text-[10px] font-medium",
        verified
          ? "border-go-500/35 bg-go-500/10 text-go-400"
          : "border-console-700 bg-console-900/50 text-ink-500",
        className,
      )}
      title={
        verified
          ? "This source has been checked against a published timetable."
          : "Not checked against a published timetable — treat as a guide."
      }
    >
      <Icon className="size-2.5 shrink-0" />
      {parts.join(" · ")}
    </span>
  );
}

/**
 * The route's own attribution, plus what was replaced to produce it.
 *
 * The override line exists because R1 — the audit's critical finding — was a
 * silent substitution of local data over correct Maps times. An override that
 * announces itself is a very different thing from one that doesn't.
 */
export function RouteProvenance({ route, className }: { route: Route; className?: string }) {
  const override = route._provenance_override;

  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
      <ProvenanceBadge provenance={route} prefix="Times" />
      {override && (
        <span
          className="text-[10px] text-ink-700"
          title={`Google Maps gave ${
            override.previous_departure_times?.[0] ?? "a departure time"
          }; the local timetable was used instead.`}
        >
          replaced {sourceLabel(override.replaced_source)}
          {override.previous_departure_times?.[0]
            ? ` (was ${override.previous_departure_times[0]})`
            : ""}
        </span>
      )}
    </div>
  );
}
