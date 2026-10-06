import { useCallback, useEffect, useRef, useState } from "react";

export interface Resource<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => Promise<void>;
  setData: (data: T) => void;
}

/** Load data on mount and whenever `load` changes, with a manual reload and local overwrite
 * after a save. Only the latest load may settle the state: an older, slower answer is dropped. */
export function useResource<T>(load: () => Promise<T>): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const latest = useRef(0);

  const reload = useCallback(async () => {
    const request = ++latest.current;
    setLoading(true);
    try {
      const loaded = await load();
      if (request !== latest.current) return;
      setData(loaded);
      setError(null);
    } catch (caught) {
      if (request === latest.current) setError(caught);
    } finally {
      if (request === latest.current) setLoading(false);
    }
  }, [load]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload, setData };
}
