"use client";

import { motion } from "framer-motion";
import { TrainFront } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";

import { Composer } from "@/components/chat/Composer";
import { JourneySidebar } from "@/components/chat/JourneySidebar";
import { MessageBubble } from "@/components/chat/MessageBubble";
import { BookRide, bookableSegment } from "@/components/journey/BookRide";
import { AgentTrace } from "@/components/trace/AgentTrace";
import { useChat } from "@/hooks/useChat";
import { useReadAloud } from "@/hooks/useReadAloud";
import type { ClarificationField } from "@/lib/types";

const WELCOME = `Welcome — I'm **CommuteAI**.

I plan train and bus journeys across Sri Lanka, watch for live disruptions, and reroute you when something goes wrong.

Ask me in **English**, **සිංහල**, or **தமிழ்**. Where are you heading?`;

export function ChatPanel({ mapsKey }: { mapsKey: string }) {
  const { messages, journey, run, busy, send, bookRide, startNewJourney, sessionId } = useChat();
  const audio = useReadAloud();

  const bottom = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);

  // Follow the conversation, but only when the commuter is already near the
  // bottom — yanking the viewport away from someone reading an earlier plan
  // is worse than letting the new message arrive off-screen.
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromBottom < 220) {
      bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [messages, run.trace.length]);

  // The composer adapts to whatever the agent last asked for.
  const awaiting = useMemo<ClarificationField | null>(() => {
    const last = messages.at(-1);
    if (!last || last.role !== "assistant" || last.kind !== "clarify") return null;
    return last.clarification ?? null;
  }, [messages]);

  // The floating action targets the most recent plan's first leg. Anchoring it
  // to the latest plan rather than to each card keeps it unambiguous about
  // which journey it books when the transcript holds several.
  const bookable = useMemo(() => {
    const lastPlan = [...messages].reverse().find((m) => m.state?.candidate_route);
    return bookableSegment(lastPlan?.state?.candidate_route);
  }, [messages]);

  return (
    <div className="mx-auto grid w-full max-w-7xl flex-1 gap-4 px-4 pb-4 lg:grid-cols-[minmax(0,1fr)_300px]">
      {/* ── Conversation ─────────────────────────────────────────────────── */}
      <section className="flex min-h-0 flex-col gap-3">
        <div
          ref={scroller}
          className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1"
          role="log"
          aria-live="polite"
          aria-label="Conversation"
        >
          {messages.length === 0 && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex gap-3"
            >
              <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg bg-signal-500/12 text-signal-400">
                <TrainFront className="size-3.5" />
              </span>
              <div className="md max-w-[85%] rounded-2xl rounded-tl-md bg-console-850/80 px-4 py-3 text-sm text-ink-300 ring-1 ring-console-700/70">
                {WELCOME.split("\n\n").map((para, i) => (
                  <p key={i} dangerouslySetInnerHTML={{ __html: markdownBold(para) }} />
                ))}
              </div>
            </motion.div>
          )}

          {messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              mapsKey={mapsKey}
              onReadAloud={audio.toggle}
              isLoadingAudio={audio.isLoading(message.id)}
              isPlayingAudio={audio.isPlaying(message.id)}
            />
          ))}

          {/* Live trace, shown only while the graph is actually running. */}
          {run.active && (
            <div className="pl-10">
              <AgentTrace
                trace={run.trace}
                current={run.current}
                active
                disruptionLevel={run.disruptionLevel}
                replanAttempts={run.replanAttempts}
              />
            </div>
          )}

          {/* Pre-trace thinking state: the request is out but no node has
              reported yet, so there is nothing for AgentTrace to draw. */}
          {busy && run.trace.length === 0 && (
            <div className="flex gap-3 pl-10">
              <div className="shimmer h-9 w-48 rounded-xl bg-console-850/60" />
            </div>
          )}

          <div ref={bottom} />
        </div>

        <Composer
          onSend={send}
          disabled={busy}
          awaiting={awaiting}
          language={journey.language}
        />
      </section>

      {/* ── Journey summary ──────────────────────────────────────────────── */}
      <JourneySidebar
        journey={journey}
        onNewJourney={startNewJourney}
        onExample={send}
        disabled={busy}
        className="lg:sticky lg:top-4 lg:self-start"
      />

      {bookable && (
        <BookRide
          pickup={bookable.pickup}
          dropoff={bookable.dropoff}
          sessionId={sessionId.current}
          busy={busy}
          onBook={(rideClass) => void bookRide(bookable.pickup, bookable.dropoff, rideClass)}
        />
      )}
    </div>
  );
}

/** Minimal **bold** rendering for the static welcome copy. */
function markdownBold(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/\*\*(.+?)\*\*/g, '<strong class="text-ink-100">$1</strong>');
}
