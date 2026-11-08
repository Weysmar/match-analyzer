/**
 * The Demos folder through the File System Access API (Chrome and Edge). The browser keeps the
 * folder's handle between visits, but asks again for the right to read it, on a click: this is an
 * import of the new replays on demand, not a synchronization.
 */
import { kvGet, kvSet } from "./store";

/** Where the game writes replays, under the player's documents. */
export const DEMOS_PATH = String.raw`Documents\My Games\Rocket League\TAGame\Demos`;
/** The first import takes the most recent ones only. */
export const IMPORT_LIMIT = 50;
/** Enough to remember years of saved replays without growing for ever. */
const KNOWN_MAX = 5000;
const HANDLE_KEY = "demos-handle";
const KNOWN_KEY = "demos-known";

export interface FileFacts {
  name: string;
  size: number;
  lastModified: number;
}

/** A file already brought, recognized without reading it. */
export function factsKey(file: FileFacts): string {
  return `${file.name}|${file.size}|${file.lastModified}`;
}

/** The replays not brought yet, most recent first, at most `limit`. */
export function newReplays<T extends FileFacts>(
  files: readonly T[],
  known: ReadonlySet<string>,
  limit = IMPORT_LIMIT,
): T[] {
  return files
    .filter((file) => file.name.toLowerCase().endsWith(".replay") && !known.has(factsKey(file)))
    .sort((a, b) => b.lastModified - a.lastModified)
    .slice(0, limit);
}

/** Adds keys to the known ones, the oldest dropped first beyond the limit. */
export function remember(known: readonly string[], added: readonly string[]): string[] {
  const merged = [...known.filter((key) => !added.includes(key)), ...added];
  return merged.slice(Math.max(0, merged.length - KNOWN_MAX));
}

// The parts of the API that TypeScript's DOM library does not describe yet.
interface PermissionDescriptor {
  mode: "read";
}
interface DemosFolder extends FileSystemDirectoryHandle {
  queryPermission(descriptor: PermissionDescriptor): Promise<PermissionState>;
  requestPermission(descriptor: PermissionDescriptor): Promise<PermissionState>;
}
interface PickerWindow {
  showDirectoryPicker(options: {
    id?: string;
    mode?: "read";
    startIn?: "documents";
  }): Promise<DemosFolder>;
}

export function supportsFolder(): boolean {
  return typeof window !== "undefined" && "showDirectoryPicker" in window;
}

export async function savedFolder(): Promise<DemosFolder | null> {
  return (await kvGet<DemosFolder>(HANDLE_KEY)) ?? null;
}

/** Asks for the folder; null when the player closes the picker. */
export async function chooseFolder(): Promise<DemosFolder | null> {
  try {
    const folder = await (window as unknown as PickerWindow).showDirectoryPicker({
      id: "demos",
      mode: "read",
      startIn: "documents",
    });
    await kvSet(HANDLE_KEY, folder);
    return folder;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return null;
    throw error;
  }
}

/** Must run during a click: the browser asks the player again at each visit. */
export async function mayRead(folder: DemosFolder): Promise<boolean> {
  if ((await folder.queryPermission({ mode: "read" })) === "granted") return true;
  return (await folder.requestPermission({ mode: "read" })) === "granted";
}

export async function replaysIn(folder: DemosFolder): Promise<File[]> {
  const files: File[] = [];
  for await (const entry of folder.values()) {
    if (entry.kind === "file" && entry.name.toLowerCase().endsWith(".replay")) {
      files.push(await (entry as FileSystemFileHandle).getFile());
    }
  }
  return files;
}

export async function knownFiles(): Promise<Set<string>> {
  return new Set((await kvGet<string[]>(KNOWN_KEY)) ?? []);
}

export async function markKnown(files: readonly FileFacts[]): Promise<void> {
  const known = (await kvGet<string[]>(KNOWN_KEY)) ?? [];
  await kvSet(KNOWN_KEY, remember(known, files.map(factsKey)));
}
