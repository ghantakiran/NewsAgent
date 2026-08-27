import { useAppStore } from '../store';
import type {
  ArticleListResponse,
  BreakingResponse,
  UDListResponse,
  EarningsListResponse,
  FeedListResponse,
  StatsResponse,
  TokenResponse,
  AlertGroupListResponse,
} from '../types';

const DEFAULT_BASE_URL = 'http://localhost:8000';

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

function getBaseUrl(): string {
  return useAppStore.getState().apiBaseUrl || DEFAULT_BASE_URL;
}

function getAuthHeaders(): Record<string, string> {
  const token = useAppStore.getState().accessToken;
  if (token) {
    return { Authorization: `Bearer ${token}` };
  }
  return {};
}

function buildQueryString(params: Record<string, unknown>): string {
  const entries = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== null
  );
  if (entries.length === 0) return '';
  const qs = entries
    .map(
      ([k, v]) =>
        `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`
    )
    .join('&');
  return `?${qs}`;
}

async function request<T>(
  method: HttpMethod,
  path: string,
  options?: { params?: Record<string, unknown>; body?: unknown }
): Promise<T> {
  const base = getBaseUrl();
  const qs = options?.params ? buildQueryString(options.params) : '';
  const url = `${base}${path}${qs}`;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...getAuthHeaders(),
  };

  const init: RequestInit = { method, headers };

  if (options?.body !== undefined) {
    init.body = JSON.stringify(options.body);
  }

  const response = await fetch(url, init);

  if (!response.ok) {
    const errorBody = await response.text().catch(() => '');
    throw new Error(
      `HTTP ${response.status}: ${response.statusText} — ${errorBody}`
    );
  }

  return response.json() as Promise<T>;
}

export const api = {
  // Generic methods
  get: <T>(path: string, params?: Record<string, unknown>) =>
    request<T>('GET', path, { params }),

  post: <T>(path: string, body?: unknown) =>
    request<T>('POST', path, { body }),

  put: <T>(path: string, body?: unknown) =>
    request<T>('PUT', path, { body }),

  patch: <T>(path: string, body?: unknown) =>
    request<T>('PATCH', path, { body }),

  delete: <T>(path: string, body?: unknown) =>
    request<T>('DELETE', path, { body }),

  // Articles
  getArticles: (params: {
    category?: string;
    ticker?: string;
    search?: string;
    hours?: number;
    limit?: number;
    filtered?: boolean;
  }) =>
    request<ArticleListResponse>('GET', '/articles', { params }),

  // Breaking news
  getBreaking: (params?: { hours?: number; limit?: number }) =>
    request<BreakingResponse>('GET', '/breaking', { params }),

  // Upgrades & downgrades
  getUpgradesDowngrades: (params?: {
    ticker?: string;
    search?: string;
    hours?: number;
    limit?: number;
  }) =>
    request<UDListResponse>('GET', '/upgrades-downgrades', { params }),

  // Earnings
  getEarnings: (params?: {
    hours?: number;
    filter?: string;
    search?: string;
  }) =>
    request<EarningsListResponse>('GET', '/earnings', { params }),

  // Catalysts
  getCatalysts: (params?: {
    type?: string;
    hours?: number;
    limit?: number;
  }) =>
    request<ArticleListResponse>('GET', '/catalysts', { params }),

  // Feeds
  getFeeds: () => request<FeedListResponse>('GET', '/feeds'),

  // Stats
  getStats: () => request<StatsResponse>('GET', '/stats'),

  // Articles by symbol
  getArticlesBySymbol: (params?: {
    symbols?: string;
    search?: string;
    limit_per?: number;
  }) =>
    request<any>('GET', '/articles/by-symbol', { params }),

  // Tickers
  getTickers: () =>
    request<{ tickers: string[] }>('GET', '/tickers'),

  // Auth
  register: (email: string, password: string) =>
    request<TokenResponse>('POST', '/auth/register', {
      body: { email, password },
    }),

  login: (email: string, password: string) =>
    request<TokenResponse>('POST', '/auth/login', {
      body: { email, password },
    }),

  // Watchlist
  getWatchlist: () =>
    request<{ tickers: string[] }>('GET', '/watchlist'),

  updateWatchlist: (tickers: string[]) =>
    request<{ tickers: string[] }>('PUT', '/watchlist', {
      body: { tickers },
    }),

  // Notifications
  registerDeviceToken: (token: string, platform: 'ios' | 'android') =>
    request<{ status: string; token: string }>('POST', '/api/v1/notifications/register-device', {
      body: { token, platform },
    }),

  unregisterDeviceToken: (token: string, platform: 'ios' | 'android') =>
    request<void>('DELETE', '/api/v1/notifications/unregister-device', {
      body: { token, platform },
    }),

  // Alerts
  getAlerts: (params?: { hours?: number; limit?: number }) =>
    request<AlertGroupListResponse>('GET', '/api/v1/alerts', { params }),
};

export function getAlertsWsUrl(tickers: string[]): string {
  const base = useAppStore.getState().apiBaseUrl || DEFAULT_BASE_URL;
  const wsBase = base.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:');
  const url = `${wsBase}/api/v1/ws/live`;
  if (tickers.length === 0) {
    return url;
  }
  const csv = tickers.map((t) => t.toUpperCase()).join(',');
  return `${url}?tickers=${encodeURIComponent(csv)}`;
}
