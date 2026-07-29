"use client";

import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Bike, Car, CircleDot, FlaskConical, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button, Spinner } from "@/components/ui/primitives";
import { fetchBookingOptions } from "@/lib/api";
import type { Route, RideClassOption } from "@/lib/types";
import { cn } from "@/lib/utils";

/** One bookable segment of a journey — always exactly one transit leg. */
export interface BookableLeg {
  index: number;
  pickup: string;
  dropoff: string;
  mode: string;
  line: string;
  distanceM: number | null;
  isFinalLeg: boolean;
}

/**
 * Every leg of a route that a ride could replace.
 *
 * A booking is scoped to ONE leg — pickup is that leg's board stop, drop-off
 * its alight stop. It is never the journey's origin and final destination,
 * unless the chosen leg happens to be the only leg or the last one.
 *
 * `route.legs` holds transit steps only; google_maps_tool never emits a
 * WALKING step as a leg, so every entry here is already a non-walking leg.
 *
 * The previous version returned `legs[0]` and nothing else. That reads as
 * leg-scoped, and on a multi-leg journey it is — but the recommended route on
 * the demo corridors is a single-leg direct train, where "the first leg" is
 * the entire 119 km Colombo Fort -> Kandy journey. The user tapped "Book a
 * ride" and got a 119 km taxi. Hence: list the legs, let them choose, and
 * carry each leg's real distance so the guard and the price mean something.
 */
export function bookableLegs(route?: Route | null): BookableLeg[] {
  const legs = route?.legs ?? [];
  return legs
    .map((leg, index) => ({
      index,
      pickup: leg.board_stop,
      dropoff: leg.alight_stop,
      mode: leg.mode,
      line: leg.line,
      distanceM: leg.distance_m ?? null,
      isFinalLeg: index === legs.length - 1,
    }))
    .filter((leg) => Boolean(leg.pickup && leg.dropoff));
}

function ClassIcon({ rideClass, className }: { rideClass: string; className?: string }) {
  if (rideClass === "bike") return <Bike className={className} />;
  if (rideClass === "car") return <Car className={className} />;
  return <CircleDot className={className} />;
}

export interface BookRideProps {
  legs: BookableLeg[];
  sessionId?: string | null;
  busy?: boolean;
  onBook: (leg: BookableLeg, rideClass: string) => void;
  className?: string;
}

function legLabel(leg: BookableLeg): string {
  const km = leg.distanceM ? ` · ${(leg.distanceM / 1000).toFixed(1)} km` : "";
  return `${leg.pickup} → ${leg.dropoff}${km}`;
}

/**
 * Floating "Book a ride" action, scoped to a single leg.
 *
 * Two choices, both one tap: which leg to replace, then which vehicle. The leg
 * list only appears when there is more than one leg, so a single-leg journey
 * is still one tap. Time is always now and the endpoints are always the leg's
 * own, so nothing else is asked — the front-loaded interrogation the planner
 * deliberately dropped is not being rebuilt here.
 *
 * The selected leg is named on the button and in the popover before anything
 * is booked, because the failure this replaces was silent: it defaulted to the
 * first leg, and on a single-leg direct train that is the whole 119 km
 * journey, quoted as a taxi with no indication of what was being booked.
 *
 * Availability is fetched per leg before classes are shown, so every option
 * offered will actually succeed.
 */
export function BookRide({
  legs,
  sessionId,
  busy = false,
  onBook,
  className,
}: BookRideProps) {
  const [open, setOpen] = useState(false);
  const [legIndex, setLegIndex] = useState(0);
  const [options, setOptions] = useState<RideClassOption[] | null>(null);
  const [alreadyBooked, setAlreadyBooked] = useState(false);
  const [scopeWarning, setScopeWarning] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selected = legs[Math.min(legIndex, Math.max(legs.length - 1, 0))];
  const legKey = selected ? `${selected.pickup}|${selected.dropoff}` : "";

  // A new plan means new legs; reset rather than carry stale availability, and
  // fall back to the first leg so the index can never point past the array.
  const routeKey = legs.map((l) => `${l.pickup}>${l.dropoff}`).join("|");
  useEffect(() => {
    setOpen(false);
    setLegIndex(0);
    setOptions(null);
    setScopeWarning(null);
    setError(null);
  }, [routeKey]);

  const load = useCallback(async () => {
    if (!selected) return;
    setLoading(true);
    setError(null);
    try {
      const result = await fetchBookingOptions(
        selected.pickup,
        selected.dropoff,
        sessionId,
        selected.distanceM,
      );
      setOptions(result.options);
      setAlreadyBooked(result.already_booked);
      setScopeWarning(result.scope_warning ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't load ride options.");
    } finally {
      setLoading(false);
    }
  }, [selected, sessionId]);

  // Refetch whenever the chosen leg changes while the panel is open — prices
  // and availability are per segment.
  useEffect(() => {
    if (open && selected) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, legKey]);

  const toggle = useCallback(() => setOpen((wasOpen) => !wasOpen), []);

  const available = options?.filter((option) => option.available) ?? [];
  if (!selected) return null;

  return (
    <div className={cn("fixed right-4 bottom-4 z-40 flex flex-col items-end gap-2", className)}>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 8, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.97 }}
            transition={{ duration: 0.18, ease: [0.2, 0.9, 0.3, 1] }}
            className="panel w-[min(20rem,calc(100vw-2rem))] overflow-hidden"
          >
            <div className="flex items-center gap-2 border-b border-glow-400/25 bg-glow-400/10 px-3 py-2">
              <FlaskConical className="size-3 shrink-0 text-glow-400" />
              <p className="text-[10px] leading-snug font-semibold text-glow-400">
                Simulated booking · production requires PickMe/Uber partner API.
              </p>
            </div>

            <div className="p-3">
              {/* Which leg. Shown only when there IS a choice, so a single-leg
                  journey stays a one-tap flow. */}
              {legs.length > 1 && (
                <>
                  <p className="eyebrow">Which leg should the ride replace?</p>
                  <div className="mt-1.5 flex flex-col gap-1">
                    {legs.map((leg) => (
                      <button
                        key={leg.index}
                        type="button"
                        onClick={() => setLegIndex(leg.index)}
                        aria-pressed={leg.index === selected.index}
                        className={cn(
                          "rounded-lg border px-2 py-1.5 text-left text-[11px] transition",
                          leg.index === selected.index
                            ? "border-signal-500/50 bg-signal-500/10 text-ink-100"
                            : "border-console-700 bg-console-900/40 text-ink-500 hover:text-ink-300",
                        )}
                      >
                        <span className="block truncate">{legLabel(leg)}</span>
                        <span className="text-[10px] text-ink-700">
                          {leg.mode === "train" ? "Train" : "Bus"}
                          {leg.line ? ` · ${leg.line}` : ""}
                          {leg.isFinalLeg ? " · final leg" : ""}
                        </span>
                      </button>
                    ))}
                  </div>
                </>
              )}

              <p className={cn("text-[11px] text-ink-500", legs.length > 1 && "mt-3")}>
                <span className="text-ink-300">{selected.pickup}</span>
                <span className="mx-1 text-ink-700">→</span>
                <span className="text-ink-300">{selected.dropoff}</span>
                {selected.distanceM ? (
                  <span className="tabular ml-1 text-ink-700">
                    ({(selected.distanceM / 1000).toFixed(1)} km)
                  </span>
                ) : null}
              </p>

              {/* Surfaced, not enforced. A leg this long is almost certainly
                  not the segment the commuter meant to replace with a taxi. */}
              {scopeWarning && (
                <p className="mt-2 flex items-start gap-1.5 rounded-lg border border-alert-500/40 bg-alert-500/10 px-2 py-1.5 text-[10px] leading-relaxed text-alert-400">
                  <AlertTriangle className="mt-px size-3 shrink-0" />
                  <span>{scopeWarning}</span>
                </p>
              )}

              {loading && (
                <p className="mt-3 flex items-center gap-2 text-xs text-ink-500">
                  <Spinner className="size-3" />
                  Checking availability…
                </p>
              )}

              {error && <p className="mt-3 text-xs text-alert-400">{error}</p>}

              {alreadyBooked && (
                <p className="mt-3 text-xs text-ink-500">
                  You&apos;ve already booked this leg. The plan below starts from the drop-off.
                </p>
              )}

              {!loading && !error && !alreadyBooked && options && available.length === 0 && (
                <p className="mt-3 text-xs text-ink-500">
                  No vehicle is available for this segment right now.
                </p>
              )}

              {!alreadyBooked && available.length > 0 && (
                <>
                  <p className="eyebrow mt-3">Pick a vehicle</p>
                  <div className="mt-2 flex flex-col gap-1.5">
                    {available.map((option) => (
                      <button
                        key={option.ride_class}
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          setOpen(false);
                          onBook(selected, option.ride_class);
                        }}
                        className="flex items-center gap-2.5 rounded-lg border border-console-700 bg-console-900/50 px-2.5 py-2 text-left transition hover:border-signal-500/50 hover:bg-signal-500/8 disabled:pointer-events-none disabled:opacity-45"
                      >
                        <ClassIcon
                          rideClass={option.ride_class}
                          className="size-3.5 shrink-0 text-ink-500"
                        />
                        <span className="flex-1 text-xs font-medium text-ink-100">
                          {option.label}
                        </span>
                        <span className="text-right">
                          <span className="tabular block text-xs font-semibold text-glow-400">
                            ~{option.currency} {option.price?.toLocaleString("en-LK")}
                          </span>
                          <span className="tabular block text-[10px] text-ink-500">
                            {option.eta_min} min away
                          </span>
                        </span>
                      </button>
                    ))}
                  </div>
                  <p className="mt-2 text-[10px] leading-relaxed text-ink-700">
                    Prices and ETAs are generated, not quoted.
                  </p>
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <Button
        variant={open ? "subtle" : "primary"}
        size="sm"
        onClick={toggle}
        disabled={busy}
        aria-expanded={open}
        className="shadow-lg shadow-console-950/40"
      >
        {busy ? <Spinner className="size-3" /> : open ? <X className="size-3" /> : <Car className="size-3" />}
        {open ? "Close" : "Book a ride"}
        {!open && (
          <span className="hidden max-w-40 truncate text-[10px] font-normal opacity-80 sm:inline">
            · {selected.pickup} → {selected.dropoff}
          </span>
        )}
      </Button>
    </div>
  );
}
