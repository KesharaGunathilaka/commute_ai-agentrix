import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

import type {
  DisruptionLevel,
  FareEstimate,
  Language,
  OptimiseFor,
  Route,
  RouteLeg,
} from "./types";

/** Merge Tailwind classes, letting later utilities win over earlier ones. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const LANGUAGE_NAMES: Record<Language, string> = {
  en: "English",
  si: "සිංහල",
  ta: "தமிழ்",
};

/** First departure and final arrival of a route — what a board would show. */
export function routeWindow(route: Route | null | undefined): { departs: string; arrives: string } {
  return {
    departs: route?.departure_times?.[0] ?? "—",
    arrives: route?.arrival_times?.at(-1) ?? "—",
  };
}

/**
 * Journey duration in minutes from the HH:MM endpoints.
 *
 * Returns null rather than a wrong number when either endpoint is missing or
 * unparseable — a route enriched from the timetable JSON can carry a "—".
 * A negative span is read as crossing midnight and wrapped, since the times
 * are clock times with no date attached.
 */
export function durationMinutes(route: Route | null | undefined): number | null {
  const { departs, arrives } = routeWindow(route);
  const start = parseHHMM(departs);
  const end = parseHHMM(arrives);
  if (start === null || end === null) return null;
  const span = end - start;
  return span < 0 ? span + 24 * 60 : span;
}

/**
 * Minutes past midnight from a clock time, or null if it isn't one.
 *
 * Two formats reach the UI and both must parse: the graph's own 24-hour
 * "07:05", and the 12-hour "7:05 AM" that the train and bus enrichment nodes
 * carry over from their upstream sources. Rejecting either silently renders
 * the journey duration as an em dash.
 */
export function parseHHMM(value: string): number | null {
  const match = /^(\d{1,2}):(\d{2})\s*(am|pm)?$/i.exec(value.trim());
  if (!match) return null;

  let hours = Number(match[1]);
  const minutes = Number(match[2]);
  const meridiem = match[3]?.toLowerCase();

  if (minutes > 59) return null;

  if (meridiem) {
    if (hours < 1 || hours > 12) return null;
    // 12 AM is midnight (0) and 12 PM is noon (12); everything else shifts by 12.
    if (meridiem === "am") hours = hours === 12 ? 0 : hours;
    else hours = hours === 12 ? 12 : hours + 12;
  } else if (hours > 23) {
    return null;
  }

  return hours * 60 + minutes;
}

/** "2h 15m" / "45m" — compact enough for a card header. */
export function formatDuration(minutes: number | null): string {
  if (minutes === null) return "—";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

/** "1.2 km" / "400 m" — metres below a kilometre stay in metres. */
export function formatDistance(metres: number | null | undefined): string {
  if (!metres && metres !== 0) return "";
  if (metres < 1000) return `${Math.round(metres)} m`;
  return `${(metres / 1000).toFixed(1)} km`;
}

/** Count the transit legs; a single-leg journey has no transfers. */
export function transferCount(route: Route | null | undefined): number {
  return Math.max(0, (route?.legs?.length ?? 1) - 1);
}

export function legLabel(leg: RouteLeg): string {
  const ref = leg.route_ref ? `No.${leg.route_ref}` : "";
  return [ref, leg.line].filter(Boolean).join(" · ") || (leg.mode === "train" ? "Train" : "Bus");
}

/** Route title for a card — the line name, falling back through description. */
export function routeTitle(route: Route | null | undefined): string {
  if (!route) return "—";
  if (route.line) return route.line;
  // Multi-leg descriptions are a multi-line block; the first line is the gist.
  const firstLine = route.description?.split("\n")[0]?.trim();
  return firstLine || route.route_id || "Route";
}

export const DISRUPTION_TONE: Record<
  DisruptionLevel,
  { label: string; text: string; border: string; bg: string; dot: string }
> = {
  clear: {
    label: "On time",
    text: "text-go-400",
    border: "border-go-500/35",
    bg: "bg-go-500/10",
    dot: "bg-go-400",
  },
  delayed: {
    label: "Delayed",
    text: "text-glow-400",
    border: "border-glow-400/40",
    bg: "bg-glow-400/10",
    dot: "bg-glow-400",
  },
  cancelled: {
    label: "Cancelled",
    text: "text-alert-400",
    border: "border-alert-500/40",
    bg: "bg-alert-500/10",
    dot: "bg-alert-400",
  },
};

export function disruptionLevel(
  status: { level?: DisruptionLevel } | null | undefined,
): DisruptionLevel {
  return status?.level ?? "clear";
}

/* ── Fares ──────────────────────────────────────────────────────────────── */

/** "LKR 169" — grouped thousands, no decimals (rupee fares aren't fractional). */
export function formatFare(amount: number, currency = "LKR"): string {
  return `${currency} ${amount.toLocaleString("en-LK", { maximumFractionDigits: 0 })}`;
}

/**
 * Headline fare text. Prefixed "from" when higher classes exist, since the
 * figure is the cheapest class rather than a single price for the journey.
 */
export function fareHeadline(fare: FareEstimate | null | undefined): string | null {
  if (!fare) return null;
  const base = formatFare(fare.amount, fare.currency);
  return fare.max_amount > fare.amount ? `from ${base}` : base;
}

/** "±25%" while the rate table is unverified, else null. */
export function fareUncertainty(fare: FareEstimate | null | undefined): string | null {
  if (!fare || fare.verified || !fare.uncertainty_pct) return null;
  return `±${Math.round(fare.uncertainty_pct * 100)}%`;
}

/* ── Client-side route sorting ──────────────────────────────────────────── */

export const SORT_OPTIONS: { id: OptimiseFor | "recommended"; label: string }[] = [
  { id: "recommended", label: "Recommended" },
  { id: "fastest", label: "Fastest" },
  { id: "cheapest", label: "Cheapest" },
  { id: "fewest_changes", label: "Fewest changes" },
];

/** Sorts after every priced route, so unknown cost never wins on price. */
const UNKNOWN_FARE = Number.POSITIVE_INFINITY;

/**
 * Re-sort routes in the browser, mirroring the backend ranker's tiebreaks.
 *
 * Client-side because a toggle that costs a 10-second graph round trip isn't
 * a toggle. The backend still ranks authoritatively for the agent's own
 * recommendation; this only reorders options the agent already returned, so
 * the two can't disagree about which routes exist.
 *
 * "recommended" returns the list untouched — that IS the backend's order.
 */
export function sortRoutes(routes: Route[], sortBy: OptimiseFor | "recommended"): Route[] {
  if (sortBy === "recommended") return routes;

  const fare = (r: Route) => r.fare_estimate?.amount ?? UNKNOWN_FARE;
  const legs = (r: Route) => r.legs?.length ?? 1;

  // Arrival CLOCK TIME, not journey duration — this mirrors the backend
  // ranker's `arrival_minutes`. The two must agree: with a departure time
  // already fixed, "fastest" means the option that gets you there soonest,
  // and having the client toggle and the server ranker disagree about that
  // word would reorder the same list two different ways.
  const arrivesAt = (r: Route) =>
    parseHHMM(routeWindow(r).arrives) ?? Number.POSITIVE_INFINITY;

  // Copy first: the caller's array is React state and must not be mutated.
  return [...routes].sort((a, b) => {
    if (sortBy === "cheapest") {
      return fare(a) - fare(b) || arrivesAt(a) - arrivesAt(b) || legs(a) - legs(b);
    }
    if (sortBy === "fastest") {
      return arrivesAt(a) - arrivesAt(b) || legs(a) - legs(b) || fare(a) - fare(b);
    }
    return legs(a) - legs(b) || arrivesAt(a) - arrivesAt(b) || fare(a) - fare(b);
  });
}

export const OPTIMISE_LABELS: Record<OptimiseFor, string> = {
  fastest: "fastest",
  cheapest: "cheapest",
  fewest_changes: "fewest changes",
};

/** Stable-enough id for list keys and message identity. */
export function uid(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);
}
