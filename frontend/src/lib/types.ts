/**
 * Wire types — the mirror of `commute_agent/api/schemas.py`.
 *
 * Fields that the backend types as `dict[str, Any]` (routes, disruptions,
 * ride quotes) are modelled here as concretely as the Python side actually
 * populates them. Everything optional is genuinely optional: a route sourced
 * from the curated timetable JSON has no polyline, a journey with no delay
 * has no disruption record, and so on.
 */

export type Language = "en" | "si" | "ta";

export type TurnKind =
  | "clarify"
  | "plan"
  | "unchanged"
  | "restart"
  | "off_topic"
  | "parse_error"
  | "error";

export type ClarificationField = "both" | "origin" | "destination" | "time" | "arrival";

export type DisruptionLevel = "clear" | "delayed" | "cancelled";

export type TransitMode = "train" | "bus";

export interface StopCoord {
  name: string;
  /** Absent when Google returned a stop with no location. */
  lat?: number;
  lng?: number;
}

/**
 * Where a value came from and whether anyone checked it.
 *
 * Mirrors `commute_agent/domain/provenance.py`. Every field is optional: an
 * older payload, or a value nobody stamped, reads as "source unrecorded,
 * unverified" — which is the honest default, not a rendering bug.
 *
 * `verified` means *this project* checked the source against a published
 * authority. It is false across the board on the data shipped today.
 */
export interface Provenance {
  source?: string | null;
  verified?: boolean;
  /** ISO date the local data was captured. Null for live sources. */
  captured_date?: string | null;
}

/** Recorded whenever local data replaces a Google Maps value. */
export interface ProvenanceOverride {
  fields: string[];
  replaced_source: string;
  new_source: string;
  timetable_route_name?: string;
  previous_departure_times?: string[];
  previous_arrival_times?: string[];
}

export interface RouteLeg extends Provenance {
  mode: TransitMode;
  line: string;
  /** Public route number, e.g. "138". Empty for most rail lines. */
  route_ref?: string;
  board_stop: string;
  alight_stop: string;
  departure: string;
  arrival: string;
  distance_m?: number;
  /** Encoded polyline for this leg alone — used to highlight one segment. */
  polyline?: string | null;
  board_coord?: { lat: number; lng: number } | null;
  alight_coord?: { lat: number; lng: number } | null;
}

export interface RouteBounds {
  north: number;
  south: number;
  east: number;
  west: number;
}

export type OptimiseFor = "fastest" | "cheapest" | "fewest_changes";

export interface FareClass {
  id: string;
  label: string;
  amount: number;
}

/**
 * An estimated fare. Never a published tariff — `estimated` is always true.
 *
 * `classes` carries real price variation (3rd vs 1st class); `uncertainty_pct`
 * carries how wrong the underlying rate table might be. They are separate
 * fields on purpose and must not be merged into a single displayed range.
 */
export interface FareEstimate extends Provenance {
  currency: string;
  /** Cheapest class — the headline figure and the cost-ranking key. */
  amount: number;
  max_amount: number;
  distance_km: number;
  classes: FareClass[];
  /** 0 once the rates are verified; otherwise the ± margin to display. */
  uncertainty_pct: number;
  mode: TransitMode;
  estimated: true;
  verified: boolean;
  source?: string;
}

export interface Route extends Provenance {
  route_id: string;
  line: string;
  stops: string[];
  /** HH:MM per stop, index-aligned with `stops`. */
  departure_times: string[];
  arrival_times: string[];
  days_of_operation: string[];
  transit_mode: TransitMode;
  vehicle_type?: string;
  description?: string;
  /** Walking metres from the last transit stop to the real destination. */
  last_mile_distance_m?: number | null;
  legs?: RouteLeg[];
  /** Encoded overview polyline. Null for non-Google-Maps routes. */
  polyline?: string | null;
  stop_coords?: StopCoord[];
  bounds?: RouteBounds | null;
  /** Null when no defensible estimate exists — treat as unknown, never free. */
  fare_estimate?: FareEstimate | null;
  /** Present when local data replaced this route's Maps-sourced times. */
  _provenance_override?: ProvenanceOverride | null;
}

/**
 * A plan's fare, summed over its legs.
 *
 * `amount` is null — never 0 — when nothing could be priced, and `complete`
 * is false whenever a leg fare was missing. Render an incomplete total as a
 * floor ("at least LKR X"), never as the price: a missing leg is unknown, not
 * free.
 *
 * `uncertainty_pct` is the widest leg's margin, not an average.
 */
export interface PlanTotalFare {
  currency: string;
  amount?: number | null;
  max_amount?: number | null;
  uncertainty_pct: number;
  complete: boolean;
  priced_legs: number;
  total_legs: number;
  estimated: boolean;
  verified: boolean;
  source?: string | null;
  captured_date?: string | null;
}

export type ProvenanceSummary = "verified" | "partially_verified" | "estimated";

/** One named plan — fastest, cheapest or balanced. */
export interface PlanVariant {
  variant_id: string;
  /** Names every strategy this route won, e.g. "Fastest & cheapest". */
  label: string;
  strategies: string[];
  blurb: string;
  route_id: string;
  line: string;
  transit_mode: TransitMode | "";
  departure_time: string;
  arrival_time: string;
  /** Null when an endpoint wouldn't parse — never a guessed duration. */
  total_duration_min?: number | null;
  total_fare: PlanTotalFare;
  legs: RouteLeg[];
  provenance_summary: ProvenanceSummary;
  missed_deadline: boolean;
  departs_before_requested: boolean;
}

export interface DisruptionRecord {
  disruption_id: string;
  train_id: string;
  affected_segment: string;
  type: string;
  delay_minutes?: number | null;
  active: boolean;
  message: string;
}

export interface DisruptionStatus {
  level: DisruptionLevel;
  disruption?: DisruptionRecord | null;
}

export interface RideQuote {
  vehicle_type: string;
  price?: number | string;
  eta_min?: number;
  available: boolean;
  currency?: string;
  distance_km?: number;
  /** Always true — ride_service.py is a dummy. Set by the backend. */
  simulated?: boolean;
  disclaimer?: string;
  source?: string | null;
  verified?: boolean;
}

/** One bookable vehicle class for a segment. */
export interface RideClassOption {
  ride_class: string;
  label: string;
  available: boolean;
  price?: number | null;
  eta_min?: number | null;
  distance_km?: number | null;
  currency: string;
  simulated: boolean;
  disclaimer: string;
}

export interface RideClassOptions {
  pickup: string;
  dropoff: string;
  options: RideClassOption[];
  /** This session already booked this exact segment — hide the action. */
  already_booked: boolean;
  simulated: boolean;
  disclaimer: string;
}

/**
 * A booking that is not a booking.
 *
 * `simulated` and `disclaimer` come from the backend, not from this client.
 * Rendering this without the badge would present a fabricated price and ETA
 * as a completed commercial transaction.
 */
export interface SimulatedBooking {
  booking_ref: string;
  pickup: string;
  dropoff: string;
  ride_class: string;
  ride_class_label: string;
  /** Minutes until the ride reaches the pickup point. */
  eta_min: number;
  /** Minutes in the vehicle. */
  ride_duration_min: number;
  price: number;
  currency: string;
  distance_km: number;
  booked_at: string;
  simulated: boolean;
  disclaimer: string;
  source?: string | null;
  verified?: boolean;
}

export interface BookingResponse {
  booking: SimulatedBooking;
  session_id: string;
  /** Drop-off is the final destination — nothing left to plan. */
  terminal: boolean;
  replanned: boolean;
  /** HH:MM the onward journey was planned from: booking + eta + ride. */
  replan_departure_time?: string | null;
  replan_offset_min: number;
  final_destination?: string | null;
  onward_plan?: AgentState | null;
  booked_segments: string[];
  message: string;
  detail?: string;
}

export interface AgentState {
  user_query: string;
  language: Language;
  origin?: string | null;
  destination?: string | null;
  requested_time?: string | null;
  expected_arrival_time?: string | null;
  preferred_mode?: string | null;
  /** What the ranker actually optimised for; null means balanced. */
  optimise_for?: OptimiseFor | null;

  candidate_route?: Route | null;
  candidate_routes: Route[];
  ranked_routes: Route[];
  alternative_route?: Route | null;
  /** Fastest / cheapest / balanced. Additive — `ranked_routes` is unchanged. */
  plan_variants?: PlanVariant[];

  disruption_status?: DisruptionStatus | null;
  original_disruption?: DisruptionStatus | null;
  replan_attempts: number;

  uber_options?: RideQuote[] | null;
  uber_last_mile?: RideQuote[] | null;
  uber_last_mile_distance_m?: number | null;
  last_mile_transit_leg?: RouteLeg | null;

  final_response_native: string;
  final_response_en: string;

  trace: string[];
  error?: string | null;
}

export interface JourneySummary {
  origin?: string | null;
  destination?: string | null;
  requested_time?: string | null;
  expected_arrival_time?: string | null;
  preferred_mode?: string | null;
  optimise_for?: OptimiseFor | null;
  language: Language;
}

export interface ChatResponse {
  session_id: string;
  kind: TurnKind;
  message: string;
  /** English gloss; equals `message` in English conversations. Used for TTS. */
  message_en: string;
  clarification?: ClarificationField | null;
  journey: JourneySummary;
  state?: AgentState | null;
  detail?: string;
}

export interface BackendConfig {
  maps_browser_key: string;
  maps_enabled: boolean;
  max_replan_attempts: number;
  supported_languages: Language[];
}

/** One `node` SSE frame — a graph node finishing mid-run. */
export interface NodeEvent {
  node: string;
  trace: string[];
  disruption_level?: DisruptionLevel | null;
  replan_attempts: number;
}

/** A chat message as the UI holds it (not a wire type). */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  /** English gloss, for read-aloud and the translation disclosure. */
  textEn?: string;
  language?: Language;
  kind?: TurnKind;
  /** Which field a `clarify` turn asked about — drives the composer's hints. */
  clarification?: ClarificationField | null;
  /** Full agent state for assistant turns that produced a plan. */
  state?: AgentState | null;
  /** Trace captured live during streaming, kept for replay after the run. */
  trace?: string[];
  error?: boolean;
  /** Set on a booking turn — rendered above `state`, which is the onward plan. */
  booking?: SimulatedBooking | null;
  /** HH:MM the onward plan departs from: booking time + eta + ride duration. */
  replanFrom?: string | null;
}
