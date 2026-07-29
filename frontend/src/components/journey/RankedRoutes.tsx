"use client";

import { Bus, Check, ListOrdered, Train } from "lucide-react";
import { useMemo, useState } from "react";

import { CollapsibleSection } from "@/components/ui/CollapsibleSection";
import type { OptimiseFor, Route } from "@/lib/types";
import {
  cn,
  durationMinutes,
  fareHeadline,
  formatDuration,
  routeTitle,
  routeWindow,
  sortRoutes,
  SORT_OPTIONS,
  transferCount,
} from "@/lib/utils";

type SortKey = OptimiseFor | "recommended";

export interface RankedRoutesProps {
  routes: Route[];
  /** Currently displayed route; null means the agent's own recommendation. */
  selectedRouteId?: string | null;
  onSelect?: (route: Route | null) => void;
  /** What the agent optimised for — seeds the initial toggle position. */
  agentOptimisedFor?: OptimiseFor | null;
  className?: string;
}

/**
 * The alternatives the ranker scored, with a sort toggle.
 *
 * Sorting happens in the browser rather than by re-running the graph: a
 * 10-second round trip is not a toggle. These are routes the agent already
 * found and priced, so reordering them client-side can't invent an option
 * the backend never saw.
 */
export function RankedRoutes({
  routes,
  selectedRouteId = null,
  onSelect,
  agentOptimisedFor = null,
  className,
}: RankedRoutesProps) {
  const [sortBy, setSortBy] = useState<SortKey>(agentOptimisedFor ?? "recommended");

  const sorted = useMemo(() => sortRoutes(routes, sortBy), [routes, sortBy]);

  if (!routes || routes.length === 0) return null;

  return (
    <CollapsibleSection
      icon={<ListOrdered className="size-3.5" />}
      title="Other options"
      meta={`${routes.length} more`}
      // Open by default when the commuter asked about cost — they came here to
      // compare, so making them click twice to see the comparison is hostile.
      defaultOpen={agentOptimisedFor === "cheapest"}
      className={className}
    >
      {/* Sort toggle */}
      <div className="flex flex-wrap items-center gap-1.5 border-t border-console-700/50 px-4 py-2.5">
        <span className="eyebrow mr-1">Sort by</span>
        {SORT_OPTIONS.map((option) => (
          <button
            key={option.id}
            type="button"
            onClick={() => setSortBy(option.id)}
            aria-pressed={sortBy === option.id}
            className={cn(
              "rounded-full border px-2.5 py-1 text-[11px] font-medium transition",
              sortBy === option.id
                ? "border-signal-500/50 bg-signal-500/12 text-signal-400"
                : "border-console-700 bg-console-900/40 text-ink-500 hover:text-ink-300",
            )}
          >
            {option.label}
          </button>
        ))}
      </div>

      <ul className="divide-y divide-console-700/50 border-t border-console-700/50">
        {sorted.map((route, index) => {
          const { departs, arrives } = routeWindow(route);
          const isTrain = route.transit_mode === "train";
          const Icon = isTrain ? Train : Bus;
          const transfers = transferCount(route);
          const fare = fareHeadline(route.fare_estimate);
          const isSelected = route.route_id === selectedRouteId;

          return (
            <li key={route.route_id ?? index}>
              <button
                type="button"
                onClick={() => onSelect?.(isSelected ? null : route)}
                className={cn(
                  "flex w-full items-center gap-3 px-4 py-2.5 text-left transition",
                  isSelected ? "bg-signal-500/8" : "hover:bg-console-800/35",
                )}
              >
                <span
                  className={cn(
                    "tabular grid size-6 shrink-0 place-items-center rounded-md text-[11px] font-bold",
                    isSelected
                      ? "bg-signal-500/20 text-signal-400"
                      : "bg-console-800 text-ink-500",
                  )}
                >
                  {isSelected ? <Check className="size-3" /> : index + 1}
                </span>

                <Icon
                  className={cn(
                    "size-3.5 shrink-0",
                    isTrain ? "text-signal-400/80" : "text-glow-400/80",
                  )}
                />

                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-ink-100">
                    {routeTitle(route)}
                  </p>
                  <p className="text-[11px] text-ink-500">
                    {transfers === 0
                      ? "Direct"
                      : `${transfers} transfer${transfers === 1 ? "" : "s"}`}
                    {" · "}
                    {formatDuration(durationMinutes(route))}
                  </p>
                </div>

                <div className="shrink-0 text-right">
                  <p className="tabular text-xs">
                    <span className="text-signal-400">{departs}</span>
                    <span className="mx-1 text-ink-700">→</span>
                    <span className="text-ink-300">{arrives}</span>
                  </p>
                  {fare && <p className="tabular text-[11px] text-glow-400">{fare}</p>}
                </div>
              </button>
            </li>
          );
        })}
      </ul>

      <p className="border-t border-console-700/50 px-4 py-2 text-[10px] text-ink-700">
        Tap an option to see it on the map. Fares are estimates.
      </p>
    </CollapsibleSection>
  );
}
