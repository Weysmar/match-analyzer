/**
 * The upload engine against the real API and the S3 emulator (T8.4). Needs `just dev-up` and
 * `just api`; run by `just test-web-it`, skipped otherwise. No worker runs: the files stop at
 * "processing", queued for parsing, which is where the engine's own work ends.
 */
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ApiError, getJson, type Schemas, sendJson } from "../../src/lib/api/client";
import { runBatch, SendError, type Transport } from "../../src/lib/upload/engine";
import { replayFile } from "../upload/fakes";

const api = process.env.WEB_IT_API_URL ?? "";
const site = process.env.SITE_URL ?? "http://localhost:3000";
const jar = new Map<string, string>();
const realFetch = globalThis.fetch;

/** What a browser adds by itself: the site's origin and the cookies the API set. */
function asBrowser(): RequestInit {
  const cookie = [...jar].map(([name, value]) => `${name}=${value}`).join("; ");
  return { headers: { Origin: site, ...(cookie ? { Cookie: cookie } : {}) } };
}

const transport: Transport = {
  async create(files) {
    const created = await sendJson<Schemas["UploadsCreated"]>(
      "POST",
      "/api/v1/uploads",
      { files },
      { base: api, init: asBrowser() },
    );
    if (!created) throw new Error("empty answer");
    return created;
  },
  async put(target, file, onProgress) {
    const response = await realFetch(target.url, {
      method: target.method,
      headers: target.headers,
      body: file,
    });
    if (!response.ok) throw new SendError(response.status);
    onProgress(1);
  },
  async complete(uploadId) {
    await sendJson("POST", "/api/v1/uploads/{upload_id}/complete", undefined, {
      base: api,
      parameters: { upload_id: uploadId },
      init: asBrowser(),
    });
  },
  async list() {
    return (
      await getJson("/api/v1/uploads", { base: api, query: { limit: 200 }, init: asBrowser() })
    ).items;
  },
};

describe.skipIf(!api)("uploads through the API and the S3 emulator", () => {
  beforeAll(() => {
    // Keeps the cookies of every answer, as a browser would.
    globalThis.fetch = async (input, options) => {
      const response = await realFetch(input, options);
      for (const line of response.headers.getSetCookie()) {
        const [pair = ""] = line.split(";");
        const at = pair.indexOf("=");
        jar.set(pair.slice(0, at), pair.slice(at + 1));
      }
      return response;
    };
  });

  afterAll(() => {
    globalThis.fetch = realFetch;
  });

  it("sends five files and queues them", async () => {
    // Distinct contents: the API recognizes a file the owner already has by its hash.
    const stamp = Date.now();
    const files = Array.from({ length: 5 }, (_, index) =>
      replayFile(`it-${stamp}-${index}.replay`, 4096 + index * 7 + (stamp % 1000)),
    );
    const items = await runBatch(files, transport, { onChange: () => {}, followForMs: 0 });
    expect(items.map((item) => item.phase)).toEqual(Array(5).fill("processing"));
    expect(jar.size).toBeGreaterThan(0);

    const listed = new Map((await transport.list()).map((upload) => [upload.upload_id, upload]));
    for (const item of items) {
      expect(listed.get(item.uploadId ?? "")?.status).toBe("uploaded");
    }
  });

  it("refuses a request from another site", async () => {
    await expect(
      sendJson(
        "POST",
        "/api/v1/uploads",
        { files: [{ name: "a.replay", size: 10 }] },
        { base: api, init: { headers: { Origin: "https://elsewhere.example" } } },
      ),
    ).rejects.toMatchObject(new ApiError(403, "bad_origin"));
  });
});
