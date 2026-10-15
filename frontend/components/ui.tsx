export function Badge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">-</span>;
  return <span className={`badge ${value}`}>{value.replace(/_/g, " ")}</span>;
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return (
    <p className="muted" role="status">
      {what}...
    </p>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="notice error" role="alert">
      {message}{" "}
      {onRetry && (
        <button onClick={onRetry} style={{ marginLeft: 8 }}>
          Retry
        </button>
      )}
    </div>
  );
}

export function fmt(iso: string): string {
  return new Date(iso).toLocaleString();
}
