"use client";

import { Info, RotateCcw } from "lucide-react";
import { useState } from "react";

import { DisruptionBanner } from "@/components/journey/DisruptionBanner";
import { PlanVariants } from "@/components/journey/PlanVariants";
import { RankedRoutes } from "@/components/journey/RankedRoutes";
import { LastMileOptions, RideOptions } from "@/components/journey/RideOptions";
import { RouteMap, RouteMapFallback } from "@/components/journey/RouteMap";
import { RouteCard } from "@/components/journey/RouteCard";
import { AgentTrace } from "@/components/trace/AgentTrace";
import { Button } from "@/components/ui/primitives";
import type { AgentState, Route } from "@/lib/types";
import { cn, disruptionLevel, OPTIMISE_LABELS } from "@/lib/utils";

/**
 * Everything the agent produced for one journey, in reading order:
 * disruption first (it changes how you read the rest), then the route(s),
 * the map, the runners-up, ride fallbacks, and finally the trace.
 */
export function JourneyPlan({
  state,
  mapsKey,
  className,
}: {
  state: AgentState;
  /** Empty string disables the map and shows the stop-list fallback. */
  mapsKey: string;
  className?: string;
}) {
  // A route the commuter picked from the alternatives list. Null means the
  // agent's own recommendation is showing — kept distinct so the headline
  // card never silently contradicts the agent's prose above it.
  const [selected, setSelected] = useState<Route | null>(null);

  const level = disruptionLevel(state.disruption_status);
  const hadDisruption = Boolean(state.original_disruption) || state.replan_attempts > 0;

  // The responder promotes a successful alternative into `candidate_route`,
  // so `alternative_route` still being distinct means the replan is worth
  // showing side by side: this is what you asked for, this is what you get.
  const alternative = state.alternative_route;
  const showComparison =
    !selected &&
    Boolean(alternative) &&
    alternative?.route_id !== state.candidate_route?.route_id;

  const recommended = alternative ?? state.candidate_route;
  const displayed = selected ?? recommended;

  // Ranked list minus whatever is already the agent's headline route.
  const others = (state.ranked_routes ?? []).filter(
    (route) => route.route_id !== recommended?.route_id,
  );

  return (
    <div className={cn("space-y-3", className)}>
      <DisruptionBanner
        status={state.disruption_status}
        replanAttempts={state.replan_attempts}
        resolved={hadDisruption && level === "clear"}
      />

      {state.optimise_for && (
        <p className="px-1 text-[11px] text-ink-500">
          Ranked by{" "}
          <span className="font-semibold text-signal-400">
            {OPTIMISE_LABELS[state.optimise_for]}
          </span>{" "}
          because you asked for it.
        </p>
      )}

      {showComparison ? (
        <div className="grid gap-3 md:grid-cols-2">
          <RouteCard route={state.candidate_route} title="Original route" disrupted />
          <RouteCard route={alternative} title="Recommended instead" recommended />
        </div>
      ) : (
        <>
          <RouteCard
            route={displayed}
            title={selected ? "Your selected option" : "Your best route"}
            recommended={!selected}
          />
          {selected && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSelected(null)}
              className="h-7 px-2 text-[11px]"
            >
              <RotateCcw className="size-3" />
              Back to the agent&apos;s recommendation
            </Button>
          )}
        </>
      )}

      {mapsKey ? (
        <RouteMap
          route={showComparison ? alternative : displayed}
          disruptedRoute={showComparison ? state.candidate_route : null}
          apiKey={mapsKey}
        />
      ) : (
        <RouteMapFallback route={showComparison ? alternative : displayed} />
      )}

      {/* Fastest / cheapest / balanced. Sits above the ranked list because it
          answers the comparison question directly; the list below is still
          the full set the ranker scored, unchanged. */}
      <PlanVariants variants={state.plan_variants} />

      <RankedRoutes
        routes={others}
        selectedRouteId={selected?.route_id ?? null}
        onSelect={setSelected}
        agentOptimisedFor={state.optimise_for}
      />

      <RideOptions
        quotes={state.uber_options}
        title="No transit fits — ride instead"
      />

      <LastMileOptions
        quotes={state.uber_last_mile}
        transitLeg={state.last_mile_transit_leg}
        distanceM={state.uber_last_mile_distance_m}
      />

      <AgentTrace
        trace={state.trace ?? []}
        replanAttempts={state.replan_attempts}
        disruptionLevel={level}
        variant="summary"
      />

      {/* Non-fatal agent notes — a scrape that failed, a timetable miss. The
          journey still planned, so this is a footnote, not an error state. */}
      {state.error && (
        <p className="flex items-start gap-2 rounded-lg border border-console-700 bg-console-900/40 px-3 py-2 text-[11px] text-ink-500">
          <Info className="mt-px size-3 shrink-0" />
          <span>{state.error}</span>
        </p>
      )}
    </div>
  );
}
