"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { fetchSpeech } from "@/lib/api";

type Status = "idle" | "loading" | "playing";

/**
 * Read-aloud playback, one clip at a time across the whole page.
 *
 * Audio is synthesised by the backend (gTTS) rather than the browser's
 * speechSynthesis, because Sinhala and Tamil voices are absent on most
 * desktop installs.
 *
 * Blob URLs are cached per message id: replaying a message the commuter has
 * already heard shouldn't re-hit the network. The cache is revoked wholesale
 * on unmount, which is the only point at which the URLs become unreachable.
 */
export function useReadAloud() {
  const [activeId, setActiveId] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>("idle");

  const audio = useRef<HTMLAudioElement | null>(null);
  const cache = useRef(new Map<string, string>());

  useEffect(() => {
    const urls = cache.current;
    return () => {
      audio.current?.pause();
      for (const url of urls.values()) URL.revokeObjectURL(url);
      urls.clear();
    };
  }, []);

  const stop = useCallback(() => {
    audio.current?.pause();
    audio.current = null;
    setActiveId(null);
    setStatus("idle");
  }, []);

  /** Play `text` for `id`, or stop if that clip is already the active one. */
  const toggle = useCallback(
    async (id: string, text: string, lang = "en") => {
      if (activeId === id && status !== "idle") {
        stop();
        return;
      }

      // Only one clip plays at a time — starting a second would talk over the first.
      audio.current?.pause();
      audio.current = null;

      setActiveId(id);
      setStatus("loading");

      try {
        let url = cache.current.get(id);
        if (!url) {
          url = await fetchSpeech(text, lang);
          cache.current.set(id, url);
        }

        const element = new Audio(url);
        element.onended = stop;
        element.onerror = stop;
        audio.current = element;

        await element.play();
        setStatus("playing");
      } catch {
        // Autoplay refusal or a TTS failure — either way there's nothing to
        // play, and the button simply returns to its resting state.
        stop();
      }
    },
    [activeId, status, stop],
  );

  return {
    toggle,
    stop,
    isLoading: (id: string) => activeId === id && status === "loading",
    isPlaying: (id: string) => activeId === id && status === "playing",
  };
}
