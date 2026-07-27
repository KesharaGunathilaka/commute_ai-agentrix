"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { resetSession, streamChat } from "@/lib/api";
import type { ChatMessage, JourneySummary, NodeEvent } from "@/lib/types";
import { uid } from "@/lib/utils";

const SESSION_KEY = "commuteai.session";

/** Live view of the graph run backing the current turn. */
export interface RunProgress {
  active: boolean;
  /** Node names in the order they fired, including repeats on a replan loop. */
  trace: string[];
  current: string | null;
  disruptionLevel: string | null;
  replanAttempts: number;
}

const IDLE_RUN: RunProgress = {
  active: false,
  trace: [],
  current: null,
  disruptionLevel: null,
  replanAttempts: 0,
};

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [journey, setJourney] = useState<JourneySummary>({ language: "en" });
  const [run, setRun] = useState<RunProgress>(IDLE_RUN);
  const [busy, setBusy] = useState(false);

  const sessionId = useRef<string | null>(null);
  const abortRef = useRef<(() => void) | null>(null);

  // Restore the session id so a page reload continues the same conversation
  // rather than silently starting a new one on the backend. Only the id is
  // persisted — the transcript is not, since replaying it would mean
  // re-rendering plans whose live disruption data has since moved on.
  useEffect(() => {
    sessionId.current = window.localStorage.getItem(SESSION_KEY);
  }, []);

  // Abort any in-flight stream when the component goes away, so a navigation
  // mid-plan doesn't leave a reader attached to a dead tree.
  useEffect(() => () => abortRef.current?.(), []);

  const rememberSession = useCallback((id: string) => {
    sessionId.current = id;
    window.localStorage.setItem(SESSION_KEY, id);
  }, []);

  const send = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || busy) return;

      setMessages((prev) => [...prev, { id: uid(), role: "user", text: trimmed }]);
      setBusy(true);
      setRun({ ...IDLE_RUN, active: true });

      abortRef.current = streamChat(trimmed, sessionId.current, {
        onNode: (event: NodeEvent) => {
          setRun({
            active: true,
            trace: event.trace,
            current: event.node,
            disruptionLevel: event.disruption_level ?? null,
            replanAttempts: event.replan_attempts,
          });
        },

        onTurn: (turn) => {
          rememberSession(turn.session_id);
          setJourney(turn.journey);

          setMessages((prev) => [
            ...prev,
            {
              id: uid(),
              role: "assistant",
              text: turn.message,
              textEn: turn.message_en,
              language: turn.journey.language,
              kind: turn.kind,
              clarification: turn.clarification ?? null,
              state: turn.state ?? null,
              // Freeze the trace onto the message so the timeline stays
              // readable after the run ends and `run` resets.
              trace: turn.state?.trace,
            },
          ]);

          setRun(IDLE_RUN);
          setBusy(false);
          abortRef.current = null;
        },

        onError: (error) => {
          setMessages((prev) => [
            ...prev,
            {
              id: uid(),
              role: "assistant",
              text: error.message,
              kind: "error",
              error: true,
            },
          ]);
          setRun(IDLE_RUN);
          setBusy(false);
          abortRef.current = null;
        },
      });
    },
    [busy, rememberSession],
  );

  const startNewJourney = useCallback(async () => {
    abortRef.current?.();
    abortRef.current = null;

    setMessages([]);
    setJourney({ language: "en" });
    setRun(IDLE_RUN);
    setBusy(false);

    const id = sessionId.current;
    if (!id) return;
    try {
      await resetSession(id);
    } catch {
      // The backend may have already evicted this session — the local clear
      // above is what the commuter actually sees, so this is not worth
      // surfacing. The next turn creates a fresh session either way.
    }
  }, []);

  return { messages, journey, run, busy, send, startNewJourney };
}
