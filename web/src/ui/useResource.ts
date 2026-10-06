import { useCallback, useEffect, useState } from "react";

export interface Resource<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => Promise<void>;
  setData: (data: T) => void;
}

/** Load data once on mount, with a manual reload and local overwrite after a save. */
export function useResource<T>(load: () => Promise<T>): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await load());
      setError(null);
    } catch (caught) {
      setError(caught);
    } finally {
      setLoading(false);
    }
  }, [load]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload, setData };
}
