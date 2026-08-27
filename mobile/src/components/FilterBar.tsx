import React from 'react';
import { ScrollView, StyleSheet, Text, TouchableOpacity } from 'react-native';
import { theme, getCategoryColor } from '../theme';

interface FilterBarProps {
  categories: string[];
  selected: string;
  onSelect: (cat: string) => void;
}

export default function FilterBar({ categories, selected, onSelect }: FilterBarProps) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.container}
    >
      {categories.map((cat) => {
        const isSelected = cat === selected;
        const color = getCategoryColor(cat);

        return (
          <TouchableOpacity
            key={cat}
            style={[
              styles.pill,
              isSelected
                ? { backgroundColor: color, borderColor: color }
                : { backgroundColor: 'transparent', borderColor: theme.colors.borderMedium },
            ]}
            onPress={() => onSelect(cat)}
            activeOpacity={0.7}
          >
            <Text
              style={[
                styles.pillText,
                { color: isSelected ? theme.colors.bgPrimary : theme.colors.textSecondary },
              ]}
            >
              {cat.charAt(0).toUpperCase() + cat.slice(1)}
            </Text>
          </TouchableOpacity>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.sm,
    gap: theme.spacing.sm,
  },
  pill: {
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.xs,
    borderRadius: theme.borderRadius.full,
    borderWidth: 1,
  },
  pillText: {
    fontSize: theme.fontSize.sm,
    fontWeight: '600',
  },
});
