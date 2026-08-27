import React, { useState } from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { theme, getCategoryColor } from '../theme';
import { relativeTime, formatTime } from '../utils';
import type { AlertGroup } from '../types';

interface AlertCardProps {
  group: AlertGroup;
}

function formatPrice(price: number | null | undefined): string | null {
  if (price === null || price === undefined) return null;
  return `$${price}`;
}

export default function AlertCard({ group }: AlertCardProps) {
  const [expanded, setExpanded] = useState(false);
  const color = getCategoryColor(group.category);

  const ticker = group.ticker?.trim() || '—';
  const price = formatPrice(group.latest?.price);
  const message = group.latest?.message?.trim();
  const history = group.history ?? [];
  const hasHistory = history.length > 0;

  const meta = [price, group.signal?.trim(), group.timeframe?.trim()].filter(Boolean);

  return (
    <TouchableOpacity
      style={[styles.card, { borderLeftColor: color }]}
      activeOpacity={hasHistory ? 0.7 : 1}
      onPress={hasHistory ? () => setExpanded((e) => !e) : undefined}
    >
      <View style={styles.topRow}>
        <Text style={styles.ticker}>{ticker}</Text>
        <View style={[styles.categoryPill, { backgroundColor: color + '22' }]}>
          <Text style={[styles.categoryText, { color }]}>{group.category.toUpperCase()}</Text>
        </View>
        {group.count > 1 && (
          <View style={styles.countBadge}>
            <Text style={styles.countText}>{`×${group.count}`}</Text>
          </View>
        )}
        <Text style={styles.time}>{relativeTime(group.last_seen)}</Text>
      </View>

      {meta.length > 0 && (
        <View style={styles.metaRow}>
          {price != null && <Text style={styles.price}>{price}</Text>}
          {group.signal?.trim() ? <Text style={styles.metaText}>{group.signal.trim()}</Text> : null}
          {group.timeframe?.trim() ? (
            <Text style={styles.metaText}>{group.timeframe.trim()}</Text>
          ) : null}
        </View>
      )}

      {message ? (
        <Text style={styles.message} numberOfLines={2}>
          {message}
        </Text>
      ) : null}

      {expanded && hasHistory && (
        <View style={styles.history}>
          {history.slice(0, 5).map((h, i) => {
            const hp = formatPrice(h.price);
            const parts = [
              formatTime(group.last_seen),
              hp,
              h.signal?.trim(),
              h.message?.trim(),
            ].filter(Boolean);
            return (
              <Text key={i} style={styles.historyRow} numberOfLines={1}>
                {parts.join('  ·  ')}
              </Text>
            );
          })}
        </View>
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: theme.colors.bgElevated,
    borderWidth: 1,
    borderColor: theme.colors.borderSubtle,
    borderLeftWidth: 3,
    borderRadius: theme.borderRadius.lg,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
    marginBottom: theme.spacing.sm,
  },
  topRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: theme.spacing.sm,
  },
  ticker: {
    color: theme.colors.textPrimary,
    fontSize: theme.fontSize.lg,
    fontWeight: 'bold',
    fontFamily: 'Courier',
  },
  categoryPill: {
    borderRadius: theme.borderRadius.full,
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 2,
  },
  categoryText: {
    fontSize: theme.fontSize.xs - 1,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  countBadge: {
    backgroundColor: theme.colors.accentBlue,
    borderRadius: theme.borderRadius.full,
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 1,
  },
  countText: {
    color: '#ffffff',
    fontSize: theme.fontSize.xs,
    fontWeight: '700',
  },
  time: {
    marginLeft: 'auto',
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.xs,
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: theme.spacing.sm,
    marginTop: theme.spacing.xs,
  },
  price: {
    color: theme.colors.textPrimary,
    fontSize: theme.fontSize.sm,
    fontWeight: '600',
    fontFamily: 'Courier',
  },
  metaText: {
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.sm,
  },
  message: {
    color: theme.colors.textSecondary,
    fontSize: theme.fontSize.sm,
    marginTop: theme.spacing.xs,
    lineHeight: 18,
  },
  history: {
    marginTop: theme.spacing.sm,
    borderTopWidth: 1,
    borderTopColor: theme.colors.borderSubtle,
    paddingTop: theme.spacing.sm,
    gap: theme.spacing.xs,
  },
  historyRow: {
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.xs,
    fontFamily: 'Courier',
  },
});
