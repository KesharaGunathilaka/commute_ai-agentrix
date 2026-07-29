"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Bike, Car, CircleDot, FlaskConical, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button, Spinner } from "@/components/ui/primitives";
import { fetchBookingOptions } from "@/lib/api";
import type { Route, RideClassOption } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * The segment a booking would replace.
 *
 * The first transit leg, always. Pickup is where that leg boards and drop-off
 * is where it alights — so there is nothing to ask about except the vehicle,
 * and the button can name the segment before it is tapped. A route with no
 * structured legs isn't bookable, because we'd be guessing at the endpoints.
 */
export function bookableSegment(route?: Route | null): { pickup: string; dropoff: string } | null {
  const leg = route?.legs?.[0];
  if (!leg?.board_stop || !leg?.alight_stop) return null;
  return { pickup: leg.board_stop, dropoff: leg.alight_stop };
}

function ClassIcon({ rideClass, className }: { rideClass: string; className?: string }) {
  if (rideClass === "bike") return <Bike className={className} />;
  if (rideClass === "car") return <Car className={className} />;
  return <CircleDot className={className} />;
}

export interface BookRideProps {
  pickup: string;
  dropoff: string;
  sessionId?: string | null;
  busy?: boolean;
  onBook: (rideClass: string) => void;
  className?: string;
}

/**
 * Floating "Book a ride" action — one tap to open, one tap to book.
 *
 * The only genuine choice is the vehicle class, so that is the only thing
 * asked. Pickup and drop-off are the leg's own endpoints and the time is now;
 * turning those into questions would rebuild the front-loaded interrogation
 * the planner deliberately dropped.
 *
 * Availability is fetched before the classes are shown so every option
 * offered will actually succeed. The stand-in backend marks some classes
 * unavailable per segment, and letting someone pick one only to be told no
 * would make this two taps and a dead end.
 */
export function BookRide({
  pickup,
  dropoff,
  sessionId,
  busy = false,
  onBook,
  className,
}: BookRideProps) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<RideClassOption[] | null>(null);
  const [alreadyBooked, setAlreadyBooked] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Re-check whenever the target segment changes: a new plan means a new first
  // leg, and stale availability would offer a ride for the previous journey.
  useEffect(() => {
    setOpen(false);
    setOptions(null);
    setError(null);
  }, [pickup, dropoff]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchBookingOptions(pickup, dropoff, sessionId);
      setOptions(result.options);
      setAlreadyBooked(result.already_booked);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't load ride options.");
    } finally {
      setLoading(false);
    }
  }, [pickup, dropoff, sessionId]);

  const toggle = useCallback(() => {
    setOpen((wasOpen) => {
      if (!wasOpen && !options) void load();
      return !wasOpen;
    });
  }, [load, options]);

  const available = options?.filter((option) => option.available) ?? [];

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
              <p className="text-[11px] text-ink-500">
                <span className="text-ink-300">{pickup}</span>
                <span className="mx-1 text-ink-700">→</span>
                <span className="text-ink-300">{dropoff}</span>
              </p>

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
                  <p className="eyebrow mt-3">Pick a vehicle — that&apos;s the only choice</p>
                  <div className="mt-2 flex flex-col gap-1.5">
                    {available.map((option) => (
                      <button
                        key={option.ride_class}
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          setOpen(false);
                          onBook(option.ride_class);
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
          <span className="hidden max-w-[10rem] truncate text-[10px] font-normal opacity-80 sm:inline">
            · {pickup}
          </span>
        )}
      </Button>
    </div>
  );
}
