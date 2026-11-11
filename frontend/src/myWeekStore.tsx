import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  addToMyWeek,
  getMyWeek,
  removeFromMyWeek,
  type MyWeek,
  type MyWeekEntry,
  type Suggestion,
} from "./api";

// Every week's chosen dishes, loaded once for the whole app. The My week tab
// and every plate+ button read and change it here, so a plate tapped on the
// Dishes tab is already green — and the dish already listed — on My week.

const titleKey = (title: string) => title.trim().toLowerCase();

type MyWeekStore = {
  data: MyWeek | null;
  error: string | null;
  // This week's entry for a dish, matched by title as the backend does.
  inThisWeek: (title: string) => MyWeekEntry | undefined;
  // Adds to `week` (a Monday), or this week; returns how many were new.
  add: (suggestions: Suggestion[], week?: string) => Promise<number>;
  remove: (entry: MyWeekEntry) => Promise<void>;
};

const MyWeekContext = createContext<MyWeekStore | null>(null);

export function MyWeekProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<MyWeek | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    return getMyWeek()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: unknown) => setError(String(e)));
  }, []);
  useEffect(() => {
    void reload();
  }, [reload]);

  const add = useCallback(
    async (suggestions: Suggestion[], week?: string) => {
      let created = 0;
      try {
        for (const s of suggestions) {
          const added = await addToMyWeek(s, week);
          if (added.created) created++;
        }
      } finally {
        await reload();
      }
      return created;
    },
    [reload],
  );

  const remove = useCallback(
    async (entry: MyWeekEntry) => {
      // Optimistic: the dish goes at once and comes back if the delete fails.
      setData((d) => d && { ...d, entries: d.entries.filter((e) => e.id !== entry.id) });
      try {
        await removeFromMyWeek(entry.id);
      } catch (e: unknown) {
        await reload();
        throw e;
      }
    },
    [reload],
  );

  const store = useMemo<MyWeekStore>(() => {
    const thisWeek = new Map(
      (data?.entries ?? [])
        .filter((e) => e.week === data?.currentWeek)
        .map((e) => [titleKey(e.suggestion.title), e]),
    );
    return {
      data,
      error,
      inThisWeek: (title) => thisWeek.get(titleKey(title)),
      add,
      remove,
    };
  }, [data, error, add, remove]);

  return <MyWeekContext.Provider value={store}>{children}</MyWeekContext.Provider>;
}

export function useMyWeekStore(): MyWeekStore {
  const store = useContext(MyWeekContext);
  if (!store) throw new Error("useMyWeekStore outside <MyWeekProvider>");
  return store;
}
