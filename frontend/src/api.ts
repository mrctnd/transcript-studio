export type Status =
  | "queued"
  | "downloading"
  | "loading_model"
  | "transcribing"
  | "completed"
  | "failed"
  | "cancelled";
export type Segment = { id: string; start: number; end: number; text: string };
export type Job = {
  id: string;
  title: string;
  source_url?: string;
  source_type: string;
  status: Status;
  progress: number;
  message?: string;
  error?: string;
  created_at: string;
  model: string;
  language: string;
  duration?: number;
  segments: Segment[];
  warnings: string[];
};
export type Health = {
  status: string;
  engine: string;
  device: string;
  dependencies: Record<string, unknown>;
  max_file_size?: number;
};

export const labels: Record<Status, string> = {
  queued: "Queued",
  downloading: "Downloading media",
  loading_model: "Preparing model",
  transcribing: "Transcribing",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const active = (status: Status) =>
  !["completed", "failed", "cancelled"].includes(status);

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch("/api" + path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const message = body?.detail ?? body?.error;
    throw new Error(
      typeof message === "string"
        ? message
        : "Request failed (" + response.status + ").",
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const json = (method: string, body: object): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export function timestamp(seconds: number) {
  const total = Math.max(0, Math.floor(seconds));
  return [Math.floor(total / 3600), Math.floor(total / 60) % 60, total % 60]
    .slice(total < 3600 ? 1 : 0)
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
}
