import { cookies } from "next/headers";
import { type CallOptions, type GetPath, type GetResult, getJson } from "./client";

/** The API's address seen from the site's server, never from the browser. */
export function apiBase(): string {
  return process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
}

/** A GET to the API on behalf of the visitor, whose cookies say who they are. */
export async function serverGet<P extends GetPath>(
  path: P,
  options: Pick<CallOptions, "parameters" | "query"> = {},
): Promise<GetResult<P>> {
  const cookieHeader = (await cookies()).toString();
  return getJson(path, {
    ...options,
    base: apiBase(),
    init: { headers: cookieHeader ? { Cookie: cookieHeader } : {}, cache: "no-store" },
  });
}
