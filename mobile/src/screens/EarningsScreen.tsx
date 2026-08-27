import React, { useState, useCallback } from 'react';
import {
  FlatList,
  Linking,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { theme } from '../theme';
import { useEarnings } from '../hooks/useApi';
import { EarningsResult } from '../types';

const FILTERS = ['All', 'Beats Only', 'Misses Only', 'Has EPS'];

function EarningsCard({ item }: { item: EarningsResult }) {
  const isBeat = item.beat_miss?.toLowerCase().includes('beat');
  const isMiss = item.beat_miss?.toLowerCase().includes('miss');
  const beatColor = isBeat
    ? theme.colors.accentGreen
    : isMiss
      ? theme.colors.accentRed
      : theme.colors.textMuted;

  return (
    <TouchableOpacity
      style={styles.card}
      onPress={() => item.url && Linking.openURL(item.url)}
      activeOpacity={0.7}
    >
      <View style={styles.cardHeader}>
        <Text style={styles.ticker}>{item.ticker}</Text>
        {item.beat_miss ? (
          <View style={[styles.beatBadge, { borderColor: beatColor }]}>
            <Text style={[styles.beatText, { color: beatColor }]}>
              {item.beat_miss.toUpperCase()}
            </Text>
          </View>
        ) : null}
      </View>
      <Text style={styles.title} numberOfLines={2}>
        {item.title}
      </Text>
      <View style={styles.metricsRow}>
        {item.eps ? (
          <Text style={styles.metric}>EPS: {item.eps}</Text>
        ) : null}
        {item.revenue ? (
          <Text style={styles.metric}>Rev: {item.revenue}</Text>
        ) : null}
      </View>
      <View style={styles.bottomRow}>
        <Text style={styles.source}>{item.source}</Text>
        <Text style={styles.date}>{item.published?.split('T')[0]}</Text>
      </View>
    </TouchableOpacity>
  );
}

export default function EarningsScreen() {
  const [filter, setFilter] = useState('All');
  const [search, setSearch] = useState('');

  const filterParam =
    filter === 'All'
      ? undefined
      : filter === 'Beats Only'
        ? 'beat'
        : filter === 'Misses Only'
          ? 'miss'
          : 'has_eps';

  const { data, isLoading, refetch, isRefetching } = useEarnings({
    filter: filterParam,
    search: search || undefined,
  });

  const results = data?.results ?? [];

  const onRefresh = useCallback(() => {
    refetch();
  }, [refetch]);

  return (
    <View style={styles.container}>
      <TextInput
        style={styles.searchBar}
        placeholder="Search earnings..."
        placeholderTextColor={theme.colors.textMuted}
        value={search}
        onChangeText={setSearch}
        autoCapitalize="none"
        autoCorrect={false}
      />

      <View style={styles.filterBar}>
        {FILTERS.map((f) => (
          <TouchableOpacity
            key={f}
            style={[
              styles.filterChip,
              filter === f && styles.filterChipActive,
            ]}
            onPress={() => setFilter(f)}
          >
            <Text
              style={[
                styles.filterText,
                filter === f && styles.filterTextActive,
              ]}
            >
              {f}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <View style={styles.refreshBar}>
        <Text style={styles.refreshText}>
          {isLoading ? 'Loading...' : `${results.length} earnings`}
        </Text>
      </View>

      <FlatList
        data={results}
        keyExtractor={(item, index) => `${item.ticker}-${index}`}
        renderItem={({ item }) => <EarningsCard item={item} />}
        refreshing={isRefetching}
        onRefresh={onRefresh}
        contentContainerStyle={results.length === 0 ? styles.empty : undefined}
        ListEmptyComponent={
          !isLoading ? (
            <Text style={styles.emptyText}>No earnings found</Text>
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
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.sm,
    gap: theme.spacing.sm,
    backgroundColor: theme.colors.bgSecondary,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
  },
  filterChip: {
    paddingHorizontal: theme.spacing.md,
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
  card: {
    backgroundColor: theme.colors.bgElevated,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: theme.spacing.xs,
  },
  ticker: {
    color: theme.colors.accentBlue,
    fontSize: theme.fontSize.lg,
    fontWeight: 'bold',
    fontFamily: 'Courier',
  },
  beatBadge: {
    borderWidth: 1,
    borderRadius: theme.borderRadius.sm,
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 2,
  },
  beatText: {
    fontSize: theme.fontSize.xs,
    fontWeight: 'bold',
  },
  title: {
    color: theme.colors.textPrimary,
    fontSize: theme.fontSize.md,
    lineHeight: 20,
    marginBottom: theme.spacing.xs,
  },
  metricsRow: {
    flexDirection: 'row',
    gap: theme.spacing.lg,
    marginBottom: theme.spacing.xs,
  },
  metric: {
    color: theme.colors.accentGold,
    fontSize: theme.fontSize.sm,
    fontFamily: 'Courier',
  },
  bottomRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  source: {
    color: theme.colors.textDim,
    fontSize: theme.fontSize.xs,
  },
  date: {
    color: theme.colors.textDim,
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
