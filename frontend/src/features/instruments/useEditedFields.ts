import { useCallback, useMemo, useState } from 'react';

/**
 * Form state that follows the server values until the user edits a field.
 * `values` = edited text where present, else the latest server text. After a successful apply call `clear()`.
 */
export function useEditedFields(server: Record<string, string>) {
  const [edited, setEdited] = useState<Record<string, string>>({});

  const values = useMemo(() => ({ ...server, ...edited }), [server, edited]);
  const dirtyKeys = useMemo(() => Object.keys(edited).filter((k) => edited[k] !== server[k]), [edited, server]);

  const set = useCallback((key: string, value: string) => setEdited((e) => ({ ...e, [key]: value })), []);
  const clear = useCallback(() => setEdited({}), []);
  const revertKey = useCallback(
    (key: string) =>
      setEdited((e) => {
        const next = { ...e };
        delete next[key];
        return next;
      }),
    [],
  );

  return { values, set, clear, revertKey, dirtyKeys, isDirty: dirtyKeys.length > 0 };
}
