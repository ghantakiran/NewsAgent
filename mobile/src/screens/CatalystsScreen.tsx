import React, { useState, useCallback } from 'react';
import {
  FlatList,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { theme } from '../theme';
import { useCatalysts } from '../hooks/useApi';
import ArticleCard from '../components/ArticleCard';

const CATALYST_TYPES = [
  'all',
  'earnings',
  'fda',
  'm&a',
  'ipo',
  'insider',
  'dividend',
  'filing',
];

export default function CatalystsScreen() {
  const [selected, setSelected] = useState('all');

  const { data, isLoading, refetch, isRefetching } = useCatalysts({
    type: selected === 'all' ? undefined : selected,
  });

  const articles = data?.articles ?? [];

  const onRefresh = useCallback(() => {
    refetch();
  }, [refetch]);

  return (
    <View style={styles.container}>
      <View style={styles.filterBar}>
        {CATALYST_TYPES.map((type) => (
          <TouchableOpacity
            key={type}
            style={[
              styles.filterChip,
              selected === type && styles.filterChipActive,
            ]}
            onPress={() => setSelected(type)}
          >
            <Text
              style={[
                styles.filterText,
                selected === type && styles.filterTextActive,
              ]}
            >
              {type.toUpperCase()}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <FlatList
        data={articles}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => <ArticleCard article={item} />}
        refreshing={isRefetching}
        onRefresh={onRefresh}
        contentContainerStyle={articles.length === 0 ? styles.empty : undefined}
        ListEmptyComponent={
          !isLoading ? (
            <Text style={styles.emptyText}>No catalysts found</Text>
          ) : null
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.colors.bgPrimary,
  },
  filterBar: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.sm,
    gap: theme.spacing.xs,
    backgroundColor: theme.colors.bgSecondary,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
  },
  filterChip: {
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: theme.spacing.xs,
    borderRadius: theme.borderRadius.full,
    backgroundColor: theme.colors.bgHover,
  },
  filterChipActive: {
    backgroundColor: theme.colors.accentBlue + '33',
    borderColor: theme.colors.accentBlue,
    borderWidth: 1,
  },
  filterText: {
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.xs,
    fontWeight: '600',
  },
  filterTextActive: {
    color: theme.colors.accentBlue,
  },
  empty: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  emptyText: {
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.md,
  },
});
