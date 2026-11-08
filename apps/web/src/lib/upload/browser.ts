/**
 * The engine's transport in the browser: the API through the site's relay, the files straight to
 * the object store. XHR, because `fetch` does not report the progress of what it sends.
 */
import { getJson, type Schemas, sendJson } from "@/lib/api/client";
import { SendError, type Transport } from "./engine";

export function xhrPut(
  target: Schemas["UploadToSend"],
  file: Blob,
  onProgress: (fraction: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open(target.method, target.url);
    for (const [name, value] of Object.entries(target.headers)) {
      request.setRequestHeader(name, value);
    }
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress(event.loaded / event.total);
    };
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        onProgress(1);
        resolve();
      } else {
        reject(new SendError(request.status));
      }
    };
    request.onerror = () => reject(new SendError(0));
    request.ontimeout = () => reject(new SendError(0));
    request.send(file);
  });
}

export const browserTransport: Transport = {
  async create(files) {
    const created = await sendJson<Schemas["UploadsCreated"]>("POST", "/api/v1/uploads", {
      files,
    });
    if (!created) throw new Error("empty answer");
    return created;
  },
  put: xhrPut,
  async complete(uploadId) {
    await sendJson("POST", "/api/v1/uploads/{upload_id}/complete", undefined, {
      parameters: { upload_id: uploadId },
    });
  },
  async list() {
    return (await getJson("/api/v1/uploads", { query: { limit: 200 } })).items;
  },
};
