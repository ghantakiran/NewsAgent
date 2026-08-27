import React, { useState, useCallback } from 'react';
import {
  FlatList,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { theme } from '../theme';
import { useArticles } from '../hooks/useApi';
import ArticleCard from '../components/ArticleCard';

const CATEGORIES = [
  'all',
  'earnings',
  'upgrade',
  'downgrade',
  'macro',
  'fda',
  'm&a',
  'ipo',
];

export default function LiveFeedScreen() {
  const [category, setCategory] = useState('all');
  const [search, setSearch] = useState('');

  const { data, isLoading, refetch, isRefetching } = useArticles({
    category: category === 'all' ? undefined : category,
    search: search || undefined,
    limit: 100,
  });

  const onRefresh = useCallback(() => {
    refetch();
  }, [refetch]);

  const articles = data?.articles ?? [];

  return (
    <View style={styles.container}>
      <TextInput
        style={styles.searchBar}
        placeholder="Search articles..."
        placeholderTextColor={theme.colors.textMuted}
        value={search}
        onChangeText={setSearch}
        autoCapitalize="none"
        autoCorrect={false}
      />

      <View style={styles.filterBar}>
        {CATEGORIES.map((cat) => (
          <TouchableOpacity
            key={cat}
            style={[
              styles.filterChip,
              category === cat && styles.filterChipActive,
            ]}
            onPress={() => setCategory(cat)}
          >
            <Text
              style={[
                styles.filterText,
                category === cat && styles.filterTextActive,
              ]}
            >
              {cat.toUpperCase()}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <View style={styles.refreshBar}>
        <Text style={styles.refreshText}>
          {isLoading ? 'Loading...' : `${articles.length} articles`}
        </Text>
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
            <Text style={styles.emptyText}>No articles found</Text>
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
  searchBar: {
    backgroundColor: theme.colors.bgElevated,
    color: theme.colors.textPrimary,
    fontSize: theme.fontSize.md,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
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
  refreshBar: {
    backgroundColor: theme.colors.bgSecondary,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
  },
  refreshText: {
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.xs,
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
