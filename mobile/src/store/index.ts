import { create } from 'zustand';

export interface AppState {
  // Auth
  accessToken: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;
  setTokens: (access: string, refresh: string) => void;
  clearTokens: () => void;

  // Watchlist
  watchlist: string[];
  addTicker: (ticker: string) => void;
  removeTicker: (ticker: string) => void;
  setWatchlist: (tickers: string[]) => void;

  // Settings
  timezone: string;
  setTimezone: (tz: string) => void;

  // API base URL
  apiBaseUrl: string;
  setApiBaseUrl: (url: string) => void;
}

export const useAppStore = create<AppState>((set) => ({
  // Auth
  accessToken: null,
  refreshToken: null,
  isAuthenticated: false,
  setTokens: (access, refresh) =>
    set({ accessToken: access, refreshToken: refresh, isAuthenticated: true }),
  clearTokens: () =>
    set({ accessToken: null, refreshToken: null, isAuthenticated: false }),

  // Watchlist
  watchlist: [],
  addTicker: (ticker) =>
    set((state) => ({
      watchlist: state.watchlist.includes(ticker)
        ? state.watchlist
        : [...state.watchlist, ticker],
    })),
  removeTicker: (ticker) =>
    set((state) => ({
      watchlist: state.watchlist.filter((t) => t !== ticker),
    })),
  setWatchlist: (tickers) => set({ watchlist: tickers }),

  // Settings
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  setTimezone: (tz) => set({ timezone: tz }),

  // API base URL
  apiBaseUrl: 'http://localhost:8000',
  setApiBaseUrl: (url) => set({ apiBaseUrl: url }),
}));
