"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Asks the server for the page again while it shows something still in progress. */
export function AutoRefresh({ everyMs }: { everyMs: number }) {
  const router = useRouter();
  useEffect(() => {
    const timer = setInterval(() => router.refresh(), everyMs);
    return () => clearInterval(timer);
  }, [router, everyMs]);
  return null;
}
