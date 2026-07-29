"use client";

import { Bike, Bus, Car, FlaskConical, Footprints, Train } from "lucide-react";

import { ProvenanceBadge } from "@/components/journey/ProvenanceBadge";
import { Panel, PanelHeader } from "@/components/ui/primitives";
import type { RideQuote, RouteLeg } from "@/lib/types";
import { cn, formatDistance, legLabel } from "@/lib/utils";

/**
 * Vehicle glyph, picked from the quote's label.
 *
 * A component rather than a function returning a component type, so the
 * element identity stays stable across renders — swapping the component type
 * mid-render would remount the icon and drop any transition on it.
 */
function VehicleIcon({ vehicleType, className }: { vehicleType: string; className?: string }) {
  const key = vehicleType.toLowerCase();
  if (key.includes("bike") || key.includes("motor")) return <Bike className={className} />;
  return <Car className={className} />;
}

function QuoteTile({ quote }: { quote: RideQuote }) {
  const currency = quote.currency ?? "LKR";

  return (
    <div
      className={cn(
        "flex-1 rounded-lg border px-3 py-2.5",
        quote.available
          ? "border-console-700 bg-console-900/50"
          : "border-console-800 bg-console-900/25 opacity-55",
      )}
    >
      <div className="flex items-center gap-1.5">
        <VehicleIcon
          vehicleType={quote.vehicle_type ?? ""}
          className="size-3.5 shrink-0 text-ink-500"
        />
        <span className="truncate text-[11px] font-medium text-ink-300 capitalize">
          {quote.vehicle_type ?? "Ride"}
        </span>
      </div>

      {quote.available ? (
        <>
          {/* "~" and "est." because these figures are generated, not quoted:
              distance for an uncurated route is rng.uniform(1.5, 24.0) and
              surge is drawn from a list. The fare block on a route card has
              always hedged; presenting these as firm prices in the same view
              held two kinds of invented number to two standards. */}
          <p className="tabular mt-1 text-sm font-semibold text-ink-100">
            ~{currency} {quote.price ?? "—"}
            <span className="ml-1 text-[10px] font-normal text-ink-500">est.</span>
          </p>
          {quote.eta_min != null && (
            <p className="tabular text-[11px] text-signal-400">~{quote.eta_min} min away</p>
          )}
        </>
      ) : (
        <p className="mt-1 text-xs text-ink-500">Unavailable</p>
      )}
    </div>
  );
}

/**
 * The simulation notice for a set of ride quotes.
 *
 * Driven by the backend's own `simulated` flag rather than assumed here, so
 * the day a real partner API is wired in the notice disappears on its own
 * instead of lingering as a lie in the other direction.
 */
function SimulationNote({ quotes }: { quotes: RideQuote[] }) {
  const simulated = quotes.find((quote) => quote.simulated);
  if (!simulated) return null;

  return (
    <p className="mt-2.5 flex items-start gap-1.5 rounded-lg border border-glow-400/25 bg-glow-400/8 px-2.5 py-1.5 text-[10px] leading-relaxed text-glow-400">
      <FlaskConical className="mt-px size-3 shrink-0" />
      <span>
        {simulated.disclaimer ||
          "Simulated quote · production requires PickMe/Uber partner API."}{" "}
        Prices, ETAs and availability are generated, not quoted.
      </span>
    </p>
  );
}

/** Ride-hailing quotes, used both for whole-trip and last-mile fallbacks. */
export function RideOptions({
  quotes,
  title,
  note,
  className,
}: {
  quotes?: RideQuote[] | null;
  title: string;
  note?: string;
  className?: string;
}) {
  if (!quotes || quotes.length === 0) return null;

  return (
    <Panel className={cn("p-4", className)}>
      <PanelHeader
        icon={<Car className="size-3.5" />}
        title={title}
        meta={note ? <span className="text-[11px] text-ink-500">{note}</span> : undefined}
      />
      <div className="mt-3 flex flex-wrap gap-2">
        {quotes.map((quote, index) => (
          <QuoteTile key={`${quote.vehicle_type}-${index}`} quote={quote} />
        ))}
      </div>
      <SimulationNote quotes={quotes} />
    </Panel>
  );
}

/** The local transit leg offered as the alternative to a last-mile ride. */
function TransitLegCard({ leg }: { leg: RouteLeg }) {
  const isTrain = leg.mode === "train";

  return (
    <div className="flex-1 rounded-lg border border-console-700 bg-console-900/50 px-3 py-2.5">
      <div className="flex items-center gap-1.5">
        {isTrain ? (
          <Train className="size-3.5 shrink-0 text-glow-400" />
        ) : (
          <Bus className="size-3.5 shrink-0 text-glow-400" />
        )}
        <span className="truncate text-[11px] font-medium text-ink-300">
          Local {leg.mode === "train" ? "train" : "bus"}
        </span>
      </div>
      <p className="mt-1 truncate text-xs font-medium text-ink-100">{legLabel(leg)}</p>
      <p className="mt-0.5 truncate text-[11px] text-ink-500">
        <span className="tabular text-signal-400">{leg.departure}</span> {leg.board_stop}
      </p>
      <p className="truncate text-[11px] text-ink-500">
        <span className="tabular text-ink-300">{leg.arrival}</span> {leg.alight_stop}
      </p>
      {leg.distance_m ? (
        <p className="mt-1 text-[11px] text-ink-500">{formatDistance(leg.distance_m)} by road</p>
      ) : null}
      <ProvenanceBadge
        provenance={leg}
        prefix={isTrain ? "Train" : "Bus"}
        className="mt-1.5"
      />
    </div>
  );
}

/**
 * The last-mile choice.
 *
 * When Google Maps found a local transit leg for the final stretch, it sits
 * beside the ride quotes as a genuine alternative. Distances are shown per
 * option rather than once for the pair — a bus's road route and a taxi's are
 * not the same distance, and averaging them would be a fiction.
 */
export function LastMileOptions({
  quotes,
  transitLeg,
  distanceM,
  className,
}: {
  quotes?: RideQuote[] | null;
  transitLeg?: RouteLeg | null;
  distanceM?: number | null;
  className?: string;
}) {
  const hasQuotes = Boolean(quotes && quotes.length > 0);
  if (!hasQuotes && !transitLeg) return null;

  const gap = formatDistance(distanceM);

  return (
    <Panel className={cn("p-4", className)}>
      <PanelHeader
        icon={<Footprints className="size-3.5" />}
        title={transitLeg ? "Last mile — choose one" : "Last mile"}
        meta={gap ? <span className="tabular text-[11px] text-ink-500">{gap}</span> : undefined}
      />

      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        {transitLeg && <TransitLegCard leg={transitLeg} />}
        {quotes?.map((quote, index) => (
          <QuoteTile key={`${quote.vehicle_type}-${index}`} quote={quote} />
        ))}
      </div>

      <SimulationNote quotes={quotes ?? []} />

      {!transitLeg && gap && (
        <p className="mt-2.5 text-[11px] text-ink-500">
          Transit drops you {gap} from your destination.
        </p>
      )}
    </Panel>
  );
}
