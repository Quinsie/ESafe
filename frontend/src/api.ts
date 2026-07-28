import type { ProfileRuntime } from "./profile";

interface ErrorPayload {
  error?: {
    code?: string;
    message?: string;
  } | null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export interface ApiEnvelope<T> {
  data: T;
  meta: {
    requestId: string;
    profile: "LIVE" | "DEMO";
    asOf: string;
  };
  error: null;
}

function cookieValue(name: string): string | undefined {
  const prefix = `${encodeURIComponent(name)}=`;
  return document.cookie
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith(prefix))
    ?.slice(prefix.length);
}

export async function apiRequest<T>(
  runtime: ProfileRuntime,
  path: string,
  init: RequestInit = {},
): Promise<ApiEnvelope<T>> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  const method = (init.method ?? "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && path !== "/auth/login") {
    const csrf = cookieValue(`esafe_${runtime.profile.toLowerCase()}_csrf`);
    if (csrf) {
      headers.set("X-CSRF-Token", decodeURIComponent(csrf));
    }
  }

  const response = await fetch(`${runtime.apiBase}${path}`, {
    ...init,
    credentials: "include",
    headers,
  });
  const payload = (await response.json().catch(() => ({}))) as ErrorPayload;
  if (!response.ok) {
    const code = payload.error?.code ?? "REQUEST_FAILED";
    const message = payload.error?.message ?? "요청을 처리하지 못했습니다.";
    if (response.status === 401 && path !== "/auth/login" && path !== "/auth/session") {
      window.dispatchEvent(new CustomEvent("esafe-session-expired"));
    }
    throw new ApiError(response.status, code, message);
  }
  return payload as ApiEnvelope<T>;
}
