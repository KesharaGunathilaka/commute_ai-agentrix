/**
 * Typed client for the CommuteAI FastAPI backend.
 *
 * Everything here runs in the browser: the API is a separate origin (:8000)
 * with CORS configured for the dev server, so there's no Next.js route handler
 * in between. That keeps the streaming path honest — an intermediary would
 * have to re-emit SSE frames, and any buffering there would defeat the live
 * trace entirely.
 */

import type {
  BackendConfig,
  BookingResponse,
  ChatResponse,
  DisruptionRecord,
  NodeEvent,
  RideClassOptions,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "http://localhost:8000";

const V1 = `${API_BASE}/api/v1`;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Turn a failed Response into an ApiError carrying the server's detail text. */
async function toApiError(res: Response): Promise<ApiError> {
  let detail = res.statusText;
  try {
    const body = await res.json();
    // FastAPI puts the message in `detail`; validation errors make it an array.
    if (typeof body?.detail === "string") detail = body.detail;
    else if (Array.isArray(body?.detail)) detail = body.detail.map((d: { msg?: string }) => d.msg).join("; ");
  } catch {
    // Body wasn't JSON — statusText is the best we have.
  }
  return new ApiError(detail, res.status);
}

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${V1}${path}`, init);
  if (!res.ok) throw await toApiError(res);
  return res.json() as Promise<T>;
}

export function fetchConfig(): Promise<BackendConfig> {
  return getJson<BackendConfig>("/config");
}

export function fetchDisruptions(): Promise<DisruptionRecord[]> {
  return getJson<DisruptionRecord[]>("/disruptions");
}

/** Non-streaming turn. The UI uses `streamChat`; this backs retries and tests. */
export function sendChat(message: string, sessionId?: string | null): Promise<ChatResponse> {
  return getJson<ChatResponse>("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId ?? null }),
  });
}

export function resetSession(sessionId: string): Promise<ChatResponse> {
  return getJson<ChatResponse>(`/session/reset?session_id=${encodeURIComponent(sessionId)}`, {
    method: "POST",
  });
}

/** Synthesise speech and return a blob URL the caller is responsible for revoking. */
export async function fetchSpeech(text: string, lang = "en"): Promise<string> {
  const res = await fetch(`${V1}/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, lang }),
  });
  if (!res.ok) throw await toApiError(res);
  return URL.createObjectURL(await res.blob());
}

/**
 * Vehicle classes bookable for one segment, with simulated prices.
 *
 * Fetched before showing the picker so only classes that will succeed are
 * offered — the dummy backend marks some unavailable per segment, and letting
 * the commuter pick one and then fail would turn one tap into two.
 */
export function fetchBookingOptions(
  pickup: string,
  dropoff: string,
  sessionId?: string | null,
): Promise<RideClassOptions> {
  const params = new URLSearchParams({ pickup, dropoff });
  if (sessionId) params.set("session_id", sessionId);
  return getJson<RideClassOptions>(`/booking/options?${params}`);
}

/**
 * Book a simulated ride and get the replanned remainder of the journey.
 *
 * Nothing is booked. The response's `simulated` flag and `disclaimer` come
 * from the server and must be rendered — see BookingCard.
 */
export function simulateBooking(input: {
  sessionId: string;
  pickup: string;
  dropoff: string;
  rideClass: string;
}): Promise<BookingResponse> {
  return getJson<BookingResponse>("/booking/simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: input.sessionId,
      pickup: input.pickup,
      dropoff: input.dropoff,
      ride_class: input.rideClass,
    }),
  });
}

export interface StreamHandlers {
  /** A graph node finished. */
  onNode?: (event: NodeEvent) => void;
  /** Terminal success — the turn is complete. */
  onTurn: (turn: ChatResponse) => void;
  /** Terminal failure, from the server or the transport. */
  onError: (error: Error) => void;
}

/**
 * Stream one conversational turn, invoking `onNode` per graph node.
 *
 * Uses `fetch` + a manual SSE parse rather than `EventSource`, for two
 * reasons: EventSource cannot be aborted cleanly mid-stream (only closed,
 * which still leaves the connection draining), and it silently auto-reconnects
 * on the server closing the stream — which for a terminal response means the
 * whole turn would run a second time.
 *
 * Returns an abort function. Calling it stops the read; the graph run itself
 * continues server-side, since a half-finished plan is not worth cancelling.
 */
export function streamChat(
  message: string,
  sessionId: string | null | undefined,
  handlers: StreamHandlers,
): () => void {
  const controller = new AbortController();
  const params = new URLSearchParams({ message });
  if (sessionId) params.set("session_id", sessionId);

  (async () => {
    let res: Response;
    try {
      res = await fetch(`${V1}/chat/stream?${params}`, {
        signal: controller.signal,
        headers: { Accept: "text/event-stream" },
      });
    } catch {
      // A network-level failure here is almost always the backend being down;
      // the underlying TypeError ("Failed to fetch") says nothing useful.
      if (!controller.signal.aborted) {
        handlers.onError(
          new ApiError(`Can't reach the agent at ${API_BASE}. Is the FastAPI server running?`),
        );
      }
      return;
    }

    if (!res.ok) {
      handlers.onError(await toApiError(res));
      return;
    }
    if (!res.body) {
      handlers.onError(new ApiError("Streaming is not supported by this browser."));
      return;
    }

    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    // SSE frames are separated by a blank line. Partial frames stay in the
    // buffer until the terminator arrives — a chunk boundary can land
    // anywhere, including mid-JSON.
    let buffer = "";

    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += value;
        let split: number;
        while ((split = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, split);
          buffer = buffer.slice(split + 2);
          dispatchFrame(frame, handlers);
        }
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        handlers.onError(err instanceof Error ? err : new Error(String(err)));
      }
    } finally {
      reader.cancel().catch(() => {});
    }
  })();

  return () => controller.abort();
}

/** Parse one `event:`/`data:` frame and route it to the right handler. */
function dispatchFrame(frame: string, handlers: StreamHandlers): void {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }

  if (dataLines.length === 0) return;

  let payload: unknown;
  try {
    payload = JSON.parse(dataLines.join("\n"));
  } catch {
    return; // Malformed frame — skip rather than tear down the stream.
  }

  if (event === "node") handlers.onNode?.(payload as NodeEvent);
  else if (event === "turn") handlers.onTurn(payload as ChatResponse);
  else if (event === "error") {
    const { message, detail } = payload as { message?: string; detail?: string };
    handlers.onError(new ApiError(message || detail || "The agent hit an error."));
  }
}
