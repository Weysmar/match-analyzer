import { notFound } from "next/navigation";
import { ApiError, type Schemas } from "@/lib/api/client";
import { serverGet } from "@/lib/api/server";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** A match sheet, on the server, with the visitor's cookies; a match that is not theirs is a 404. */
export async function sheet(id: string): Promise<Schemas["MatchSheet"]> {
  if (!UUID.test(id)) notFound();
  try {
    return await serverGet("/api/v1/matches/{match_id}", { parameters: { match_id: id } });
  } catch (error) {
    // Someone else's match looks like one that does not exist, as the API answers.
    if (error instanceof ApiError && [400, 401, 404, 422].includes(error.status)) notFound();
    throw error;
  }
}
