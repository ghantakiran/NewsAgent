export interface Article {
  id: string;
  title: string;
  url: string;
  source: string;
  published: string; // ISO datetime
  category: string;
  tickers: string[];
  summary: string;
  fetched_at?: string;
}

export interface ArticleListResponse {
  articles: Article[];
  total: number;
  deduped_count: number;
}

export interface UpgradeDowngrade {
  ticker: string;
  firm: string;
  action: string;
  old_rating: string;
  new_rating: string;
  price_target: string;
  published: string;
  source_url: string;
  source: string;
  grade: string;
}

export interface UDListResponse {
  upgrades: UpgradeDowngrade[];
  downgrades: UpgradeDowngrade[];
  mixed: UpgradeDowngrade[];
  unresolved: UpgradeDowngrade[];
  total: number;
  grade_counts: Record<string, number>;
}

export interface EarningsResult {
  ticker: string;
  title: string;
  url: string;
  source: string;
  published: string;
  eps: string;
  revenue: string;
  beat_miss: string;
}

export interface EarningsListResponse {
  results: EarningsResult[];
  total: number;
  by_ticker: Record<string, EarningsResult[]>;
}

export interface Feed {
  name: string;
  url: string;
  category: string;
  enabled: boolean;
  last_fetched?: string;
  error?: string;
  is_custom: boolean;
}

export interface FeedListResponse {
  feeds: Feed[];
  errors: Record<string, string>;
}

export interface StatsResponse {
  article_count: number;
  active_sources: number;
  source_counts: Record<string, number>;
  last_fetch_time?: string;
  fetch_errors: Record<string, string>;
  refresh_interval: number;
}

export interface BreakingResponse {
  articles: Article[];
  count: number;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface AlertItem {
  ticker: string;
  category: string;
  signal: string;
  timeframe: string;
  price: number | null;
  message: string;
  extra?: Record<string, unknown>;
}

export interface AlertGroup {
  group_id: string;
  category: string;
  ticker: string;
  timeframe: string;
  signal: string;
  count: number;
  first_seen: string; // ISO datetime
  last_seen: string; // ISO datetime
  latest: AlertItem;
  history: AlertItem[];
}

export interface AlertGroupListResponse {
  groups: AlertGroup[];
  total: number;
}

export interface AlertWsMessage {
  type: 'alert';
  event: 'new' | 'update';
  data: AlertGroup;
}
