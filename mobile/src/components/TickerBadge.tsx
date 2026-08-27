import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { theme } from '../theme';

interface TickerBadgeProps {
  ticker: string;
  variant?: 'default' | 'breaking';
}

export default function TickerBadge({ ticker, variant = 'default' }: TickerBadgeProps) {
  const isBreaking = variant === 'breaking';
  const bgColor = isBreaking ? theme.colors.accentRed : theme.colors.accentBlue;

  return (
    <View style={[styles.badge, { backgroundColor: bgColor + '22', borderColor: bgColor }]}>
      <Text style={[styles.text, { color: bgColor }]}>{ticker}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 2,
    borderRadius: theme.borderRadius.sm,
    borderWidth: 1,
    marginRight: theme.spacing.xs,
  },
  text: {
    fontSize: theme.fontSize.xs,
    fontWeight: 'bold',
    fontFamily: 'Courier',
  },
});
