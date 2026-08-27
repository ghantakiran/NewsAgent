import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { theme } from '../theme';
import PulseIndicator from './PulseIndicator';

interface RefreshBarProps {
  articleCount: number;
  lastFetchTime?: string;
  refreshInterval: number;
}

export default function RefreshBar({ articleCount, lastFetchTime, refreshInterval }: RefreshBarProps) {
  return (
    <View style={styles.bar}>
      <PulseIndicator />
      <Text style={styles.count}>{articleCount} articles</Text>
      {lastFetchTime ? (
        <Text style={styles.meta}>Last: {lastFetchTime}</Text>
      ) : null}
      <Text style={styles.meta}>Refresh: {refreshInterval}s</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: theme.colors.bgElevated,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.sm,
    gap: theme.spacing.md,
  },
  count: {
    color: theme.colors.textPrimary,
    fontSize: theme.fontSize.sm,
    fontWeight: '600',
  },
  meta: {
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.xs,
  },
});
