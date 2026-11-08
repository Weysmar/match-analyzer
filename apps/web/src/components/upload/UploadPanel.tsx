"use client";

import { useTranslations } from "next-intl";
import { type DragEvent, useCallback, useEffect, useId, useRef, useState } from "react";
import { browserTransport } from "@/lib/upload/browser";
import {
  chooseFolder,
  DEMOS_PATH,
  knownFiles,
  markKnown,
  mayRead,
  newReplays,
  replaysIn,
  savedFolder,
  supportsFolder,
} from "@/lib/upload/demos";
import { type NamedBlob, newItems, runBatch } from "@/lib/upload/engine";
import { MAX_FILES, splitBatch } from "@/lib/upload/precheck";
import { type Item, summary } from "@/lib/upload/state";
import { SignInPrompt } from "../account/SignInPrompt";
import { UploadList } from "./UploadList";

type Folder = Awaited<ReturnType<typeof savedFolder>>;
type FolderState = "unsupported" | "none" | "saved";

export function UploadPanel({ signedIn, epic }: { signedIn: boolean; epic: boolean }) {
  const t = useTranslations("upload");
  const inputId = useId();
  const [batches, setBatches] = useState<{ id: number; items: Item[] }[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  // Known after the first render only: the server cannot tell which browser it serves.
  const [folderState, setFolderState] = useState<FolderState | null>(null);
  const [folderBusy, setFolderBusy] = useState(false);
  const nextBatch = useRef(0);

  useEffect(() => {
    if (!supportsFolder()) {
      setFolderState("unsupported");
      return;
    }
    savedFolder().then((folder) => setFolderState(folder ? "saved" : "none"));
  }, []);

  const send = useCallback(async (files: readonly NamedBlob[]): Promise<Item[]> => {
    const id = nextBatch.current;
    nextBatch.current += 1;
    const items = newItems(files);
    setBatches((current) => [{ id, items }, ...current]);
    return runBatch(
      files,
      browserTransport,
      {
        onChange: (latest) =>
          setBatches((current) =>
            current.map((batch) => (batch.id === id ? { id, items: latest } : batch)),
          ),
      },
      items,
    );
  }, []);

  const sendChosen = useCallback(
    (chosen: readonly File[]) => {
      if (chosen.length === 0) return;
      const { kept, left } = splitBatch(chosen);
      setNotice(left > 0 ? t("tooMany", { max: MAX_FILES, left }) : null);
      void send(kept);
    },
    [send, t],
  );

  async function importFolder(folder: Folder | null) {
    if (!folder) return;
    setFolderBusy(true);
    try {
      if (!(await mayRead(folder))) {
        setNotice(t("folder.denied"));
        return;
      }
      setFolderState("saved");
      const fresh = newReplays(await replaysIn(folder), await knownFiles());
      if (fresh.length === 0) {
        setNotice(t("folder.nothingNew"));
        return;
      }
      setNotice(t("folder.found", { count: fresh.length }));
      const items = await send(fresh);
      // Anything the API took, or refused for good, is not offered again; failures are.
      await markKnown(fresh.filter((_, index) => items[index]?.phase !== "failed"));
    } catch {
      setNotice(t("folder.error"));
    } finally {
      setFolderBusy(false);
    }
  }

  function onDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setDragging(false);
    sendChosen([...event.dataTransfer.files]);
  }

  const items = batches.flatMap((batch) => batch.items);
  const counts = summary(items);

  return (
    <div className="flex flex-col gap-6">
      <section
        aria-labelledby={`${inputId}-title`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`flex flex-col items-center gap-4 rounded-xl border-2 border-dashed px-4 py-10 text-center transition-colors ${
          dragging
            ? "border-slate-900 bg-slate-50 dark:border-slate-100 dark:bg-slate-900"
            : "border-slate-300 dark:border-slate-700"
        }`}
      >
        <h2 id={`${inputId}-title`} className="text-lg font-semibold">
          {t("drop.title")}
        </h2>
        <p className="max-w-md text-sm text-slate-600 dark:text-slate-400">
          {t("drop.hint", { max: MAX_FILES })}
        </p>
        <div className="flex flex-wrap justify-center gap-3">
          <label
            htmlFor={inputId}
            className="cursor-pointer rounded-lg bg-slate-900 px-4 py-2 font-medium text-white hover:bg-slate-700 has-focus-visible:outline-2 has-focus-visible:outline-offset-2 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
          >
            {t("drop.choose")}
          </label>
          <input
            id={inputId}
            type="file"
            accept=".replay"
            multiple
            className="sr-only"
            onChange={(event) => {
              sendChosen([...(event.target.files ?? [])]);
              event.target.value = "";
            }}
          />
          {folderState === "none" || folderState === "saved" ? (
            <button
              type="button"
              disabled={folderBusy}
              onClick={async () => {
                const folder = folderState === "saved" ? await savedFolder() : null;
                await importFolder(folder ?? (await chooseFolder()));
              }}
              className="rounded-lg border border-slate-300 px-4 py-2 font-medium hover:bg-slate-100 disabled:opacity-50 dark:border-slate-700 dark:hover:bg-slate-800"
            >
              {folderState === "saved" ? t("folder.importNew") : t("folder.choose")}
            </button>
          ) : null}
          {folderState === "saved" ? (
            <button
              type="button"
              disabled={folderBusy}
              onClick={async () => importFolder(await chooseFolder())}
              className="rounded-lg px-4 py-2 text-sm text-slate-600 underline hover:text-slate-900 disabled:opacity-50 dark:text-slate-400 dark:hover:text-slate-100"
            >
              {t("folder.change")}
            </button>
          ) : null}
        </div>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {folderState === "unsupported"
            ? t("folder.unsupported", { path: DEMOS_PATH })
            : t("folder.where", { path: DEMOS_PATH })}
        </p>
      </section>

      <p role="status" className="min-h-5 text-sm text-slate-700 dark:text-slate-300">
        {notice}
      </p>

      {items.length > 0 ? (
        <section className="flex flex-col gap-3" aria-label={t("list.title")}>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            {t("list.summary", {
              ready: counts.ready + counts.partial + counts.duplicate,
              processing: counts.checking + counts.waiting + counts.sending + counts.processing,
              problems: counts.rejected + counts.failed,
            })}
          </p>
          <UploadList items={items} />
        </section>
      ) : null}

      {!signedIn && counts.ready + counts.partial + counts.duplicate > 0 ? (
        <SignInPrompt epic={epic} returnTo="/matches" />
      ) : null}

      <p className="text-sm text-slate-500 dark:text-slate-400">{t("console")}</p>
    </div>
  );
}
