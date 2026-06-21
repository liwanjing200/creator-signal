export function Flash({ success, error }: { success?: string; error?: string }) {
  if (!success && !error) return null;
  return <div className={`flash ${error ? "flash-error" : "flash-success"}`}>{error ?? success}</div>;
}

