import React from 'react';
import { Linking, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { theme } from '../theme';
import { EarningsResult } from '../types';
import { relativeTime } from '../utils';

interface EarningsCardProps {
  earnings: EarningsResult;
}

function getBeatMissStyle(beatMiss: string): { label: string; icon: string; color: string } {
  const bm = beatMiss.toLowerCase();
  if (bm.includes('beat')) return { label: 'BEAT', icon: '▲', color: theme.colors.accentGreen };
  if (bm.includes('miss')) return { label: 'MISS', icon: '▼', color: theme.colors.accentRed };
  return { label: 'IN-LINE', icon: '●', color: theme.colors.textMuted };
}

export default function EarningsCard({ earnings }: EarningsCardProps) {
  const bm = getBeatMissStyle(earnings.beat_miss);

  const handlePress = () => {
    Linking.openURL(earnings.url);
  };

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.ticker}>{earnings.ticker}</Text>
        <Text style={styles.time}>{relativeTime(earnings.published)}</Text>
        <Text style={styles.source}>{earnings.source}</Text>
      </View>

      <TouchableOpacity onPress={handlePress} activeOpacity={0.7}>
        <Text style={styles.title} numberOfLines={2}>
          {earnings.title}
        </Text>
      </TouchableOpacity>

      <View style={styles.metricsRow}>
        <View style={styles.metric}>
          <Text style={styles.metricLabel}>EPS</Text>
          <Text style={styles.metricValue}>{earnings.eps}</Text>
        </View>
        <View style={styles.metric}>
          <Text style={styles.metricLabel}>Revenue</Text>
          <Text style={styles.metricValue}>{earnings.revenue}</Text>
        </View>
        <View style={[styles.bmBadge, { backgroundColor: bm.color + '22', borderColor: bm.color }]}>
          <Text style={[styles.bmText, { color: bm.color }]}>
            {bm.icon} {bm.label}
          </Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: theme.colors.bgElevated,
    borderWidth: 1,
    borderColor: theme.colors.borderMedium,
    borderRadius: theme.borderRadius.lg,
    padding: theme.spacing.lg,
    marginHorizontal: theme.spacing.lg,
    marginVertical: theme.spacing.sm,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.3,
    shadowRadius: 4,
    elevation: 4,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: theme.spacing.sm,
    gap: theme.spacing.sm,
  },
  ticker: {
    color: theme.colors.accentBlue,
    fontSize: theme.fontSize.xl,
    fontWeight: 'bold',
    fontFamily: 'Courier',
  },
  time: {
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.xs,
  },
  source: {
    color: theme.colors.textDim,
    fontSize: theme.fontSize.xs,
    marginLeft: 'auto',
  },
  title: {
    color: theme.colors.textPrimary,
    fontSize: theme.fontSize.md,
    lineHeight: 20,
    marginBottom: theme.spacing.md,
  },
  metricsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: theme.spacing.lg,
  },
  metric: {
    alignItems: 'center',
  },
  metricLabel: {
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.xs,
    marginBottom: 2,
  },
  metricValue: {
    color: theme.colors.textPrimary,
    fontSize: theme.fontSize.lg,
    fontWeight: '600',
    fontFamily: 'Courier',
  },
  bmBadge: {
    marginLeft: 'auto',
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.xs,
    borderRadius: theme.borderRadius.md,
    borderWidth: 1,
  },
  bmText: {
    fontSize: theme.fontSize.sm,
    fontWeight: 'bold',
  },
});
