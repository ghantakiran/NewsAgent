import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { theme, getCategoryColor } from '../theme';

interface CategoryBadgeProps {
  category: string;
}

export default function CategoryBadge({ category }: CategoryBadgeProps) {
  const color = getCategoryColor(category);

  return (
    <View style={[styles.badge, { backgroundColor: color + '22', borderColor: color }]}>
      <Text style={[styles.text, { color }]}>{category.toUpperCase()}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 2,
    borderRadius: theme.borderRadius.full,
    borderWidth: 1,
  },
  text: {
    fontSize: theme.fontSize.xs - 1,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
});
