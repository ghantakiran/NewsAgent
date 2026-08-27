import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { theme } from '../theme';
import { UpgradeDowngrade } from '../types';
import { relativeTime } from '../utils';
import GradeBadge from './GradeBadge';

interface UDRowProps {
  ud: UpgradeDowngrade;
}

function getActionColor(action: string): string {
  const a = action.toLowerCase();
  if (a.includes('upgrade')) return theme.colors.accentGreen;
  if (a.includes('downgrade')) return theme.colors.accentRed;
  return theme.colors.accentGold;
}

export default function UDRow({ ud }: UDRowProps) {
  const actionColor = getActionColor(ud.action);

  return (
    <View style={styles.row}>
      <View style={styles.leftCol}>
        <Text style={[styles.ticker, { color: actionColor }]}>{ud.ticker}</Text>
        <Text style={styles.relTime}>{relativeTime(ud.published)}</Text>
      </View>

      <View style={styles.midCol}>
        <Text style={styles.firm} numberOfLines={1}>{ud.firm}</Text>
        <View style={styles.ratingRow}>
          <Text style={styles.oldRating}>{ud.old_rating}</Text>
          <Text style={styles.arrow}> → </Text>
          <Text style={styles.newRating}>{ud.new_rating}</Text>
        </View>
      </View>

      <View style={styles.rightCol}>
        {ud.price_target ? (
          <Text style={styles.priceTarget}>${ud.price_target}</Text>
        ) : null}
        <GradeBadge grade={ud.grade} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: theme.colors.bgElevated,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
  },
  leftCol: {
    width: 64,
    marginRight: theme.spacing.md,
  },
  ticker: {
    fontSize: theme.fontSize.lg,
    fontWeight: 'bold',
    fontFamily: 'Courier',
  },
  relTime: {
    fontSize: theme.fontSize.xs,
    color: theme.colors.textMuted,
    marginTop: 2,
  },
  midCol: {
    flex: 1,
    marginRight: theme.spacing.md,
  },
  firm: {
    color: theme.colors.textSecondary,
    fontSize: theme.fontSize.sm,
    marginBottom: 2,
  },
  ratingRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  oldRating: {
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.sm,
  },
  arrow: {
    color: theme.colors.textDim,
    fontSize: theme.fontSize.sm,
  },
  newRating: {
    color: theme.colors.textPrimary,
    fontSize: theme.fontSize.sm,
    fontWeight: '600',
  },
  rightCol: {
    alignItems: 'flex-end',
    gap: theme.spacing.xs,
  },
  priceTarget: {
    color: theme.colors.textPrimary,
    fontSize: theme.fontSize.md,
    fontWeight: '600',
    fontFamily: 'Courier',
  },
});
