"use client";

import { useEffect, useState } from "react";
import { ApiError, getJson } from "@/lib/api/client";
import { loadView, type Match2d } from "@/lib/view2d/document";

export type ViewStatus = "loading" | "ready" | "unavailable" | "error";

/** A match's 2D view: its short URL from the API, then the document from the store. */
export function useView(matchId: string): { status: ViewStatus; view: Match2d | null } {
  const [status, setStatus] = useState<ViewStatus>("loading");
  const [view, setView] = useState<Match2d | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { url } = await getJson("/api/v1/matches/{match_id}/view", {
          parameters: { match_id: matchId },
        });
        const loaded = await loadView(url);
        if (!cancelled) {
          setView(loaded);
          setStatus("ready");
        }
      } catch (error) {
        if (cancelled) return;
        setStatus(error instanceof ApiError && error.status === 404 ? "unavailable" : "error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [matchId]);

  return { status, view };
}
