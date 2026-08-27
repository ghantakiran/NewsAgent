import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';

export function useArticles(params: {
  category?: string;
  ticker?: string;
  search?: string;
  hours?: number;
  limit?: number;
  filtered?: boolean;
}) {
  return useQuery({
    queryKey: ['articles', params],
    queryFn: () => api.getArticles(params),
    refetchInterval: 15000,
  });
}

export function useBreaking(params?: { hours?: number; limit?: number }) {
  return useQuery({
    queryKey: ['breaking', params],
    queryFn: () => api.getBreaking(params),
    refetchInterval: 15000,
  });
}

export function useUpgradesDowngrades(params?: {
  ticker?: string;
  search?: string;
  hours?: number;
  limit?: number;
}) {
  return useQuery({
    queryKey: ['upgrades-downgrades', params],
    queryFn: () => api.getUpgradesDowngrades(params),
    refetchInterval: 15000,
  });
}

export function useEarnings(params?: {
  hours?: number;
  filter?: string;
  search?: string;
}) {
  return useQuery({
    queryKey: ['earnings', params],
    queryFn: () => api.getEarnings(params),
    refetchInterval: 15000,
  });
}

export function useCatalysts(params?: {
  type?: string;
  hours?: number;
  limit?: number;
}) {
  return useQuery({
    queryKey: ['catalysts', params],
    queryFn: () => api.getCatalysts(params),
    refetchInterval: 15000,
  });
}

export function useFeeds() {
  return useQuery({
    queryKey: ['feeds'],
    queryFn: () => api.getFeeds(),
    refetchInterval: 30000,
  });
}

export function useStats() {
  return useQuery({
    queryKey: ['stats'],
    queryFn: () => api.getStats(),
    refetchInterval: 15000,
  });
}

export function useTickers() {
  return useQuery({
    queryKey: ['tickers'],
    queryFn: () => api.getTickers(),
    refetchInterval: 60000,
  });
}
