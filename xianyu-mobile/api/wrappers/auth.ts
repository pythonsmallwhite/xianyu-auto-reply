import { getApiClient, extractError } from './client';
import type { AuthUser } from '@/stores/auth';

export interface LoginResponse {
  success: boolean;
  message?: string;
  token?: string | null;
  refresh_token?: string | null;
  user_id?: number | null;
  username?: string | null;
  is_admin?: boolean | null;
  account_limit?: number | null;
}

interface VerifyResponse {
  authenticated: boolean;
  user_id?: number;
  username?: string;
  is_admin?: boolean;
  account_limit?: number | null;
}

export async function login(
  username: string,
  password: string,
): Promise<LoginResponse> {
  const client = await getApiClient();
  const { data, error } = (await (client.POST as any)('/api/v1/auth/login', {
    body: { username, password },
  })) as { data?: LoginResponse; error?: unknown };

  if (error) throw await extractError(error);
  return data as LoginResponse;
}

export async function verifyToken(): Promise<VerifyResponse> {
  const client = await getApiClient();
  const { data } = (await (client.GET as any)('/api/v1/auth/verify')) as {
    data?: VerifyResponse;
    error?: unknown;
  };
  return data as VerifyResponse;
}

export async function logout(): Promise<void> {
  const client = await getApiClient();
  await (client.POST as any)('/api/v1/auth/logout');
}

/** 将 LoginResponse 的平铺字段转为 AuthUser */
export function extractUser(resp: LoginResponse): AuthUser | null {
  if (resp.user_id == null || resp.username == null) return null;
  return {
    user_id: resp.user_id,
    username: resp.username,
    is_admin: resp.is_admin ?? false,
    account_limit: resp.account_limit ?? null,
  };
}
