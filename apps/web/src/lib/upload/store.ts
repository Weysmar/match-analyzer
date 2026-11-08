/**
 * A key-value store in IndexedDB, the only browser storage that keeps a folder handle. Small
 * enough that a dependency would not pay for itself. Every failure reads as "nothing stored": a
 * private window or blocked storage must not stop the uploads.
 */
const DATABASE = "match-analyzer";
const STORE = "kv";

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function run<T>(mode: IDBTransactionMode, act: (store: IDBObjectStore) => IDBRequest<T>) {
  const database = await open();
  try {
    return await new Promise<T>((resolve, reject) => {
      const request = act(database.transaction(STORE, mode).objectStore(STORE));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  } finally {
    database.close();
  }
}

export async function kvGet<T>(key: string): Promise<T | undefined> {
  try {
    return (await run("readonly", (store) => store.get(key))) as T | undefined;
  } catch {
    return undefined;
  }
}

export async function kvSet(key: string, value: unknown): Promise<void> {
  try {
    await run("readwrite", (store) => store.put(value, key));
  } catch {
    // Not remembered: the next visit asks again.
  }
}
