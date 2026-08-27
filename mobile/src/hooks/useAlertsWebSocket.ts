import { useEffect, useRef, useState } from 'react';
import { api, getAlertsWsUrl } from '../api/client';
import type { AlertGroup, AlertWsMessage } from '../types';

const INITIAL_BACKOFF_MS = 1000;
const BACKOFF_MULTIPLIER = 1.6;
const MAX_BACKOFF_MS = 15000;

function groupsToSortedArray(map: Map<string, AlertGroup>): AlertGroup[] {
  return Array.from(map.values()).sort((a, b) =>
    a.last_seen < b.last_seen ? 1 : a.last_seen > b.last_seen ? -1 : 0
  );
}

export default function useAlertsWebSocket(tickers: string[]): {
  groups: AlertGroup[];
  connected: boolean;
} {
  const [groups, setGroups] = useState<AlertGroup[]>([]);
  const [connected, setConnected] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const groupsMapRef = useRef<Map<string, AlertGroup>>(new Map());
  const backoffRef = useRef(INITIAL_BACKOFF_MS);

  // Stable dependency: join tickers so we compare by value, not array identity.
  const tickersSignature = tickers.join(',');

  useEffect(() => {
    mountedRef.current = true;
    backoffRef.current = INITIAL_BACKOFF_MS;
    groupsMapRef.current = new Map();

    const tickerList = tickersSignature ? tickersSignature.split(',') : [];

    const upsert = (group: AlertGroup) => {
      groupsMapRef.current.set(group.group_id, group);
      if (mountedRef.current) {
        setGroups(groupsToSortedArray(groupsMapRef.current));
      }
    };

    const clearReconnectTimer = () => {
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };

    const teardownSocket = () => {
      const ws = wsRef.current;
      if (ws) {
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        try {
          ws.close();
        } catch {
          // ignore close errors
        }
        wsRef.current = null;
      }
    };

    const scheduleReconnect = () => {
      if (!mountedRef.current) return;
      clearReconnectTimer();
      const delay = backoffRef.current;
      backoffRef.current = Math.min(
        Math.round(backoffRef.current * BACKOFF_MULTIPLIER),
        MAX_BACKOFF_MS
      );
      reconnectTimerRef.current = setTimeout(() => {
        reconnectTimerRef.current = null;
        connect();
      }, delay);
    };

    const connect = () => {
      if (!mountedRef.current) return;
      teardownSocket();

      const ws = new WebSocket(getAlertsWsUrl(tickerList));
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        backoffRef.current = INITIAL_BACKOFF_MS;
        setConnected(true);
      };

      ws.onmessage = (event: WebSocketMessageEvent) => {
        if (!mountedRef.current) return;
        let parsed: unknown;
        try {
          parsed = JSON.parse(event.data as string);
        } catch {
          return;
        }
        const msg = parsed as AlertWsMessage;
        if (msg && msg.type === 'alert' && msg.data) {
          upsert(msg.data);
        }
      };

      ws.onerror = () => {
        if (!mountedRef.current) return;
        setConnected(false);
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setConnected(false);
        scheduleReconnect();
      };
    };

    // Seed state with backfill, then open the live socket.
    api
      .getAlerts({ hours: 24, limit: 200 })
      .then((res) => {
        if (!mountedRef.current) return;
        for (const group of res.groups) {
          groupsMapRef.current.set(group.group_id, group);
        }
        setGroups(groupsToSortedArray(groupsMapRef.current));
      })
      .catch(() => {
        // Backfill failure is non-fatal; live socket still provides updates.
      });

    connect();

    return () => {
      mountedRef.current = false;
      clearReconnectTimer();
      teardownSocket();
    };
  }, [tickersSignature]);

  return { groups, connected };
}
