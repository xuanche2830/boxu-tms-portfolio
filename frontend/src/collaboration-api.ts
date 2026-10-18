/** Account and runtime contracts. Business panels still have a separate typing backlog. */
export type Role = 'owner' | 'employee' | 'partner';

export interface Identity {
  user: {
    id: string;
    username: string;
    display_name: string;
    role: Role;
    organization_id: string;
    active: boolean;
    must_change_password: boolean;
  };
  organization: { id: string; name: string };
  csrf: string;
  expires_at: string;
  storage: string;
  demo: boolean;
}

export interface SpaceStatus {
  setup_required: boolean;
  version: string;
  demo: boolean;
  desktop: boolean;
  demo_url: string;
  work_url: string;
}

export class HttpError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
  }
}

export async function request<T>(path: string, init: RequestInit = {}, identity?: Identity | null): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  headers.set('X-TMS-Client', 'collaboration-v1');
  if (identity) {
    headers.set('X-CSRF-Token', identity.csrf);
    headers.set('X-Expected-User', identity.user.id);
  }
  const response = await fetch('/api/collab' + path, { ...init, credentials: 'same-origin', headers });
  if (!response.ok) {
    const body: { detail?: unknown } = await response.json().catch(() => ({}));
    throw new HttpError(typeof body.detail === 'string' ? body.detail : '请检查必填内容与字段格式', response.status);
  }
  return response.json() as Promise<T>;
}
