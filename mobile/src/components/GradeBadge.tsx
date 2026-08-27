import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { theme } from '../theme';

interface GradeBadgeProps {
  grade: string;
}

function getGradeColor(grade: string): string {
  switch (grade.toUpperCase()) {
    case 'A+':
      return theme.colors.accentGreen;
    case 'A':
      return theme.colors.accentBlue;
    case 'B':
      return theme.colors.accentGold;
    case 'C':
    default:
      return theme.colors.textMuted;
  }
}

export default function GradeBadge({ grade }: GradeBadgeProps) {
  const color = getGradeColor(grade);

  return (
    <View style={[styles.badge, { borderColor: color }]}>
      <Text style={[styles.text, { color }]}>{grade}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 2,
    borderRadius: theme.borderRadius.full,
    borderWidth: 1,
    backgroundColor: 'transparent',
  },
  text: {
    fontSize: theme.fontSize.xs,
    fontWeight: 'bold',
  },
});
