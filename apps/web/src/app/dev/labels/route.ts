/**
 * The labeling mode's export (T12.7): writes one match's verdicts into `tests/fixtures/labels/`,
 * never versioned. In development only: a production build answers 404, whatever is asked. The
 * file is checked against the format and named from its match and detector, never from the request.
 */
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileNameOf, parseLabelFile } from "@/lib/view2d/labels";

// `next dev` runs from apps/web.
const FOLDER = process.env.LABELS_DIR ?? path.resolve(process.cwd(), "../../tests/fixtures/labels");

export async function POST(request: Request): Promise<Response> {
  if (process.env.NODE_ENV !== "development") return new Response(null, { status: 404 });
  // Only this site's own pages, as for the API.
  if (request.headers.get("origin") !== new URL(request.url).origin) {
    return Response.json({ error: "forbidden" }, { status: 403 });
  }
  const file = parseLabelFile(await request.json().catch(() => null));
  if (file === null) return Response.json({ error: "invalid_labels" }, { status: 422 });
  await mkdir(FOLDER, { recursive: true });
  const name = fileNameOf(file);
  await writeFile(path.join(FOLDER, name), `${JSON.stringify(file, null, 2)}\n`, "utf-8");
  return Response.json({ file: name, labels: file.labels.length });
}
