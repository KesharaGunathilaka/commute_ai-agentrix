"use client";

import { ArrowRight, Bus, Clock, Footprints, Repeat, Ticket, Train } from "lucide-react";

import { Badge, Panel, TimeChip } from "@/components/ui/primitives";
import type { FareEstimate, Route } from "@/lib/types";
import {
  cn,
  durationMinutes,
  fareHeadline,
  fareUncertainty,
  formatDistance,
  formatDuration,
  formatFare,
  legLabel,
  routeTitle,
  routeWindow,
  transferCount,
} from "@/lib/utils";

/**
 * Fare block: headline price, per-class breakdown, and an honesty line.
 *
 * The "estimated" wording is not decoration — these figures come from a
 * modelled rate table, not a published tariff, and a commuter budgeting a
 * day's travel deserves to know which they're looking at.
 */
function FareBlock({ fare }: { fare: FareEstimate }) {
  const headline = fareHeadline(fare);
  const margin = fareUncertainty(fare);

  return (
    <div className="mt-3 rounded-lg border border-console-700/60 bg-console-900/40 px-3 py-2.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="eyebrow flex items-center gap-1.5">
          <Ticket className="size-3" />
          Est. fare
        </span>
        <span className="tabular text-sm font-semibold text-glow-400">
          {headline}
          {margin && <span className="ml-1 text-[10px] font-normal text-ink-500">{margin}</span>}
        </span>
      </div>

      {fare.classes.length > 1 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {fare.classes.map((cls) => (
            <span
              key={cls.id}
              className="rounded border border-console-700 bg-console-850 px-1.5 py-0.5 text-[10px] text-ink-300"
            >
              {cls.label}{" "}
              <span className="tabular font-semibold text-ink-100">
                {formatFare(cls.amount, fare.currency)}
              </span>
            </span>
          ))}
        </div>
      )}

      <p className="mt-2 text-[10px] leading-relaxed text-ink-700">
        Estimated from {fare.distance_km} km
        {fare.verified ? " using published rates." : " — rates unverified, treat as a guide."}
      </p>
    </div>
  );
}

export interface RouteCardProps {
  route?: Route | null;
  title: string;
  /** Dims the card and marks the header — used for the superseded route. */
  disrupted?: boolean;
  /** Highlights the card as the agent's pick. */
  recommended?: boolean;
  className?: string;
}

/**
 * The headline route: mode, timing window, duration, and every leg.
 *
 * When a disruption forces a replan, two of these sit side by side — the
 * original marked `disrupted`, the replacement marked `recommended` — so the
 * commuter can see exactly what changed rather than being told.
 */
export function RouteCard({
  route,
  title,
  disrupted = false,
  recommended = false,
  className,
}: RouteCardProps) {
  if (!route) return null;

  const { departs, arrives } = routeWindow(route);
  const duration = formatDuration(durationMinutes(route));
  const transfers = transferCount(route);
  const isTrain = route.transit_mode === "train";
  const ModeIcon = isTrain ? Train : Bus;
  const legs = route.legs ?? [];

  return (
    <Panel
      className={cn(
        "relative overflow-hidden p-4",
        // A ring rather than a glow. Emitted light only reads as emphasis
        // against a dark ground; on white the same shadow just muddies the
        // card edge. A crisp accent ring says "this one" more clearly.
        recommended && "border-signal-500/50 ring-1 ring-signal-500/20",
        disrupted && "opacity-75",
        className,
      )}
    >
      {recommended && (
        <span
          aria-hidden
          className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-signal-500 to-transparent"
        />
      )}

      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "grid size-8 place-items-center rounded-lg",
              disrupted
                ? "bg-alert-500/10 text-alert-400"
                : "bg-signal-500/10 text-signal-400",
            )}
          >
            <ModeIcon className="size-4" />
          </span>
          <div>
            <p className="eyebrow">{title}</p>
            <p className="truncate text-sm font-semibold text-ink-100" title={routeTitle(route)}>
              {routeTitle(route)}
            </p>
          </div>
        </div>

        <Badge tone={disrupted ? "alert" : isTrain ? "signal" : "glow"}>
          {isTrain ? "Train" : "Bus"}
        </Badge>
      </div>

      {/* Timing window — the departure-board row. */}
      <div className="mt-4 flex items-center gap-3 rounded-lg border border-console-700/60 bg-console-900/50 px-3 py-2.5">
        <div className="text-center">
          <p className="eyebrow mb-0.5">Departs</p>
          <TimeChip value={departs} tone="signal" className="text-base" />
        </div>

        <div className="flex flex-1 flex-col items-center gap-1">
          <span className="flex items-center gap-1 text-[11px] font-medium text-ink-500">
            <Clock className="size-3" />
            {duration}
          </span>
          <span aria-hidden className="flex w-full items-center gap-1">
            <span className="h-px flex-1 bg-console-600" />
            <ArrowRight className="size-3 shrink-0 text-ink-700" />
            <span className="h-px flex-1 bg-console-600" />
          </span>
          <span className="text-[11px] text-ink-500">
            {transfers === 0 ? "Direct" : `${transfers} transfer${transfers === 1 ? "" : "s"}`}
          </span>
        </div>

        <div className="text-center">
          <p className="eyebrow mb-0.5">Arrives</p>
          <TimeChip value={arrives} className="text-base" />
        </div>
      </div>

      {route.fare_estimate && <FareBlock fare={route.fare_estimate} />}

      {/* Per-leg boarding instructions. */}
      {legs.length > 0 && (
        <ol className="mt-3 space-y-2">
          {legs.map((leg, index) => {
            const LegIcon = leg.mode === "train" ? Train : Bus;
            return (
              <li key={`${leg.line}-${index}`} className="flex gap-2.5">
                <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-md bg-console-800 text-ink-300">
                  <LegIcon className="size-3" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-ink-100">{legLabel(leg)}</p>
                  <p className="truncate text-[11px] text-ink-500">
                    <span className="tabular text-signal-400">{leg.departure}</span>{" "}
                    {leg.board_stop}
                    <span className="mx-1 text-ink-700">→</span>
                    <span className="tabular text-ink-300">{leg.arrival}</span>{" "}
                    {leg.alight_stop}
                  </p>
                </div>
                {legs.length > 1 && index < legs.length - 1 && (
                  <Repeat className="mt-1 size-3 shrink-0 text-ink-700" />
                )}
              </li>
            );
          })}
        </ol>
      )}

      {/* A trailing walk means transit doesn't quite reach the destination. */}
      {route.last_mile_distance_m ? (
        <p className="mt-3 flex items-center gap-1.5 border-t border-console-700/60 pt-2.5 text-[11px] text-ink-500">
          <Footprints className="size-3 shrink-0" />
          {formatDistance(route.last_mile_distance_m)} walk from the last stop
        </p>
      ) : null}
    </Panel>
  );
}
