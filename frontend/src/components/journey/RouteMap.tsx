"use client";

import {
  APIProvider,
  ColorScheme,
  Map,
  Marker,
  Polyline,
  useMap,
} from "@vis.gl/react-google-maps";
import { MapPinned } from "lucide-react";
import { useEffect, useMemo } from "react";

import { Panel, PanelHeader } from "@/components/ui/primitives";
import { boundsOf, decodePolyline, type LatLng } from "@/lib/polyline";
import type { Route } from "@/lib/types";
import { cn } from "@/lib/utils";

/* ── Marker icons ──────────────────────────────────────────────────────────
   Built as data URIs rather than `google.maps.SymbolPath` constants, because
   those live on the `google` global and reading them during render can run
   before the SDK finishes loading. A data URI is just a string — always safe.
   ────────────────────────────────────────────────────────────────────────── */

function dotIcon(fill: string, ring: string, size = 14): string {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">` +
    `<circle cx="${size / 2}" cy="${size / 2}" r="${size / 2 - 2.5}" fill="${fill}" stroke="${ring}" stroke-width="2.5"/>` +
    `</svg>`;
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}

/* Endpoints are a filled cyan disc ringed in white; intermediate stops invert
   that. White rings rather than dark ones — the ring's job is to separate the
   marker from the map's own pale roads and landmasses. */
const ICON_ENDPOINT = dotIcon("#0891b2", "#ffffff", 18);
const ICON_STOP = dotIcon("#ffffff", "#0e7490", 12);

const SRI_LANKA_CENTRE = { lat: 7.4, lng: 80.7 };

/** Pans and zooms the map to contain `points` whenever they change. */
function FitBounds({ points }: { points: LatLng[] }) {
  const map = useMap();

  useEffect(() => {
    if (!map || points.length === 0) return;

    const box = boundsOf(points);
    if (!box) return;

    // A single-point route has a zero-area box; fitBounds would zoom to the
    // maximum. Centre on it at a sensible street-level zoom instead.
    if (box.north === box.south && box.east === box.west) {
      map.setCenter({ lat: box.north, lng: box.east });
      map.setZoom(14);
      return;
    }

    map.fitBounds(box, { top: 48, bottom: 32, left: 32, right: 32 });
  }, [map, points]);

  return null;
}

export interface RouteMapProps {
  route?: Route | null;
  /** Drawn in rose over the main line — the segment reported as disrupted. */
  disruptedRoute?: Route | null;
  apiKey: string;
  className?: string;
}

/**
 * Interactive route map.
 *
 * Renders the journey's overview polyline with a marker at every transit
 * stop, endpoints emphasised. When a disruption is in play the affected
 * route is overlaid in rose so the two are directly comparable.
 */
export function RouteMap({ route, disruptedRoute, apiKey, className }: RouteMapProps) {
  // Prefer the encoded polyline; fall back to joining the stop coordinates so
  // a route without geometry still shows its shape, roughly.
  const points = useMemo<LatLng[]>(() => {
    const fromPolyline = decodePolyline(route?.polyline);
    if (fromPolyline.length > 0) return fromPolyline;

    return (route?.stop_coords ?? [])
      .filter((s): s is { name: string; lat: number; lng: number } =>
        typeof s.lat === "number" && typeof s.lng === "number")
      .map(({ lat, lng }) => ({ lat, lng }));
  }, [route]);

  const stops = useMemo(
    () =>
      (route?.stop_coords ?? []).filter(
        (s): s is { name: string; lat: number; lng: number } =>
          typeof s.lat === "number" && typeof s.lng === "number",
      ),
    [route],
  );

  const hasGeometry = points.length > 0 || stops.length > 0;

  if (!hasGeometry) {
    return (
      <Panel className={cn("p-4", className)}>
        <PanelHeader icon={<MapPinned className="size-3.5" />} title="Route map" />
        <p className="mt-3 text-sm text-ink-500">
          No map data for this route — it came from the timetable archive rather than live
          routing.
        </p>
      </Panel>
    );
  }

  return (
    <Panel className={cn("overflow-hidden", className)}>
      <div className="flex items-center justify-between gap-3 px-4 pt-4 pb-3">
        <PanelHeader icon={<MapPinned className="size-3.5" />} title="Route map" />
        <div className="flex items-center gap-3 text-[11px] text-ink-500">
          <span className="flex items-center gap-1.5">
            <span className="h-0.5 w-4 rounded-full bg-signal-500" />
            Your route
          </span>
          {disruptedRoute && (
            <span className="flex items-center gap-1.5">
              <span className="h-0.5 w-4 rounded-full bg-alert-500" />
              Disrupted
            </span>
          )}
        </div>
      </div>

      <div className="h-[340px] w-full sm:h-[400px]">
        <APIProvider apiKey={apiKey}>
          <Map
            defaultCenter={SRI_LANKA_CENTRE}
            defaultZoom={8}
            colorScheme={ColorScheme.LIGHT}
            gestureHandling="cooperative"
            disableDefaultUI
            zoomControl
            reuseMaps
            className="size-full"
          >
            <FitBounds points={points} />

            {/* White casing beneath the main line. On a light map the route
                crosses pale roads of similar value, and this halo is what
                keeps the line traceable where they overlap. */}
            {route?.polyline && (
              <Polyline
                encodedPath={route.polyline}
                strokeColor="#ffffff"
                strokeOpacity={0.95}
                strokeWeight={9}
                zIndex={1}
              />
            )}
            {route?.polyline && (
              <Polyline
                encodedPath={route.polyline}
                strokeColor="#0891b2"
                strokeOpacity={1}
                strokeWeight={5}
                zIndex={2}
              />
            )}

            {disruptedRoute?.polyline && (
              <Polyline
                encodedPath={disruptedRoute.polyline}
                strokeColor="#e11d48"
                strokeOpacity={0.85}
                strokeWeight={4}
                zIndex={3}
              />
            )}

            {stops.map((stop, index) => {
              const isEndpoint = index === 0 || index === stops.length - 1;
              return (
                <Marker
                  key={`${stop.name}-${index}`}
                  position={{ lat: stop.lat, lng: stop.lng }}
                  title={stop.name}
                  icon={isEndpoint ? ICON_ENDPOINT : ICON_STOP}
                  zIndex={isEndpoint ? 6 : 4}
                />
              );
            })}
          </Map>
        </APIProvider>
      </div>
    </Panel>
  );
}

/** Stop-list shown in place of the map when no Maps browser key is set. */
export function RouteMapFallback({
  route,
  className,
}: {
  route?: Route | null;
  className?: string;
}) {
  const stops = route?.stops ?? [];
  if (stops.length === 0) return null;

  return (
    <Panel className={cn("p-4", className)}>
      <PanelHeader
        icon={<MapPinned className="size-3.5" />}
        title="Route"
        meta={<span className="text-[11px] text-ink-500">{stops.length} stops</span>}
      />
      <ol className="mt-3 space-y-0">
        {stops.map((stop, index) => {
          const isEndpoint = index === 0 || index === stops.length - 1;
          return (
            <li key={`${stop}-${index}`} className="relative flex items-center gap-3 py-1.5">
              {index < stops.length - 1 && (
                <span
                  aria-hidden
                  className="absolute top-6 left-[5px] h-[calc(100%-0.75rem)] w-px bg-console-700"
                />
              )}
              <span
                className={cn(
                  "z-10 size-2.5 shrink-0 rounded-full",
                  isEndpoint ? "bg-signal-500" : "border border-signal-500/50 bg-console-850",
                )}
              />
              <span
                className={cn(
                  "truncate text-sm",
                  isEndpoint ? "font-medium text-ink-100" : "text-ink-300",
                )}
              >
                {stop}
              </span>
              <span className="tabular ml-auto text-xs text-ink-500">
                {route?.departure_times?.[index] ?? ""}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-3 border-t border-console-700/60 pt-2.5 text-[11px] text-ink-500">
        Set <code className="text-ink-300">GOOGLE_MAPS_BROWSER_KEY</code> in your <code className="text-ink-300">.env</code> to
        see this route on a map.
      </p>
    </Panel>
  );
}
