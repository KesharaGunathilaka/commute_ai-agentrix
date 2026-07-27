"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import type { Language } from "@/lib/types";

/**
 * Microphone dictation via the Web Speech API.
 *
 * Browser-only and Chromium-only in practice — Firefox has no implementation
 * and Safari's is partial. `supported` is false everywhere else, and callers
 * hide the mic button rather than offering a control that silently fails.
 *
 * BCP-47 tags, not the backend's two-letter codes: the recogniser needs a
 * region to pick an acoustic model.
 */
const RECOGNITION_LOCALE: Record<Language, string> = {
  en: "en-IN", // Closest widely-supported model for Sri Lankan English.
  si: "si-LK",
  ta: "ta-LK",
};

// The spec's types aren't in TS's DOM lib yet, and the constructor is still
// vendor-prefixed in Chromium. Only the surface actually used is declared.
interface SpeechRecognitionAlternative {
  transcript: string;
}
interface SpeechRecognitionResult {
  readonly length: number;
  isFinal: boolean;
  [index: number]: SpeechRecognitionAlternative;
}
interface SpeechRecognitionResultList {
  readonly length: number;
  [index: number]: SpeechRecognitionResult;
}
interface SpeechRecognitionEventLike extends Event {
  resultIndex: number;
  results: SpeechRecognitionResultList;
}
interface SpeechRecognitionErrorEventLike extends Event {
  error: string;
}
interface SpeechRecognitionLike extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

/** No-op subscribe: speech-API availability is fixed for the session. */
function subscribeNever(): () => void {
  return () => {};
}

function getRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const FRIENDLY_ERRORS: Record<string, string> = {
  "not-allowed": "Microphone access was blocked. Allow it in your browser settings.",
  "service-not-allowed": "Microphone access was blocked. Allow it in your browser settings.",
  "no-speech": "I didn't catch anything — try again.",
  "audio-capture": "No microphone found.",
  network: "Speech recognition needs a network connection.",
};

export interface UseSpeechInput {
  supported: boolean;
  listening: boolean;
  /** Live partial transcript while speaking; cleared when the phrase settles. */
  interim: string;
  error: string | null;
  start: (language?: Language) => void;
  stop: () => void;
  clearError: () => void;
}

/**
 * @param onResult Called with each finalised phrase. Fires more than once if
 *   the speaker pauses mid-sentence, so callers should append, not replace.
 */
export function useSpeechInput(onResult: (transcript: string) => void): UseSpeechInput {
  // Read through useSyncExternalStore rather than an effect: the value is
  // client-only, so the server snapshot must be `false` to keep hydration
  // consistent, and this avoids the extra render an effect-then-setState pass
  // would cost. The subscribe callback is a no-op — support never changes
  // during a session.
  const supported = useSyncExternalStore(
    subscribeNever,
    () => getRecognitionCtor() !== null,
    () => false,
  );

  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);

  const recognition = useRef<SpeechRecognitionLike | null>(null);
  // Held in a ref so the recogniser's long-lived handlers always call the
  // current callback — re-registering them on every render would restart
  // recognition mid-phrase.
  const onResultRef = useRef(onResult);
  useEffect(() => {
    onResultRef.current = onResult;
  }, [onResult]);

  // Stop the microphone if the composer unmounts mid-phrase.
  useEffect(() => () => recognition.current?.abort(), []);

  const start = useCallback((language: Language = "en") => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) return;

    // Drop any previous instance — reusing one that has already ended puts
    // Chromium's recogniser into an unrecoverable state.
    recognition.current?.abort();

    const instance = new Ctor();
    instance.lang = RECOGNITION_LOCALE[language] ?? RECOGNITION_LOCALE.en;
    instance.continuous = false;
    instance.interimResults = true;
    instance.maxAlternatives = 1;

    instance.onresult = (event) => {
      let pending = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const transcript = result[0]?.transcript ?? "";
        if (result.isFinal) {
          const settled = transcript.trim();
          if (settled) onResultRef.current(settled);
        } else {
          pending += transcript;
        }
      }
      setInterim(pending);
    };

    instance.onerror = (event) => {
      // Aborting deliberately raises this too; it isn't a failure worth showing.
      if (event.error === "aborted") return;
      setError(FRIENDLY_ERRORS[event.error] ?? `Voice input failed (${event.error}).`);
      setListening(false);
      setInterim("");
    };

    instance.onend = () => {
      setListening(false);
      setInterim("");
    };

    recognition.current = instance;
    setError(null);
    setInterim("");

    try {
      instance.start();
      setListening(true);
    } catch {
      // start() throws if called while already running — treat as a no-op.
      setListening(false);
    }
  }, []);

  const stop = useCallback(() => {
    // stop() lets the final phrase settle and fire; abort() would discard it.
    recognition.current?.stop();
    setListening(false);
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return { supported, listening, interim, error, start, stop, clearError };
}
