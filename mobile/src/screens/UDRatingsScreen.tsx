import React, { useState } from 'react';
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
import { useUpgradesDowngrades } from '../hooks/useApi';
import { UpgradeDowngrade } from '../types';
import GradeBadge from '../components/GradeBadge';

function UDRow({ item }: { item: UpgradeDowngrade }) {
  return (
    <TouchableOpacity
      style={styles.row}
      onPress={() => item.source_url && Linking.openURL(item.source_url)}
      activeOpacity={0.7}
    >
      <View style={styles.rowHeader}>
        <Text style={styles.ticker}>{item.ticker}</Text>
        <GradeBadge grade={item.grade} />
      </View>
      <Text style={styles.firm}>{item.firm}</Text>
      <Text style={styles.action}>{item.action}</Text>
      <View style={styles.ratings}>
        <Text style={styles.ratingLabel}>
          {item.old_rating} {' \u2192 '} {item.new_rating}
        </Text>
        {item.price_target ? (
          <Text style={styles.pt}>PT: {item.price_target}</Text>
        ) : null}
      </View>
      <Text style={styles.source}>{item.source}</Text>
    </TouchableOpacity>
  );
}

export default function UDRatingsScreen() {
  const [search, setSearch] = useState('');

  const { data, isLoading, refetch, isRefetching } = useUpgradesDowngrades({
    ticker: undefined,
    search: search || undefined,
  });

  const upgrades = data?.upgrades ?? [];
  const downgrades = data?.downgrades ?? [];
  const mixed = data?.mixed ?? [];
  const total = data?.total ?? 0;
  const gradeCounts = data?.grade_counts ?? {};

  const sections = [
    { key: 'upgrades', label: '\u25B2 UPGRADES', color: theme.colors.accentGreen, items: upgrades },
    { key: 'downgrades', label: '\u25BC DOWNGRADES', color: theme.colors.accentRed, items: downgrades },
    { key: 'mixed', label: '\u25CF MIXED', color: theme.colors.accentGold, items: mixed },
  ];

  const allItems = sections.flatMap((s) =>
    [{ type: 'header' as const, ...s }, ...s.items.map((item) => ({ type: 'item' as const, item, key: s.key }))]
  );

  return (
    <View style={styles.container}>
      <TextInput
        style={styles.searchBar}
        placeholder="Search by ticker or firm..."
        placeholderTextColor={theme.colors.textMuted}
        value={search}
        onChangeText={setSearch}
        autoCapitalize="characters"
        autoCorrect={false}
      />

      <View style={styles.statsBar}>
        <Text style={styles.statsText}>
          {isLoading ? 'Loading...' : `${total} ratings`}
        </Text>
        {Object.keys(gradeCounts).length > 0 && (
          <Text style={styles.statsText}>
            {Object.entries(gradeCounts)
              .map(([g, c]) => `${g}: ${c}`)
              .join('  ')}
          </Text>
        )}
      </View>

      <FlatList
        data={allItems}
        keyExtractor={(item, index) => {
          if (item.type === 'header') return `header-${item.key}`;
          return `${item.key}-${index}`;
        }}
        renderItem={({ item }) => {
          if (item.type === 'header') {
            if (item.items.length === 0) return null;
            return (
              <View style={[styles.sectionHeader, { borderLeftColor: item.color }]}>
                <Text style={[styles.sectionTitle, { color: item.color }]}>
                  {item.label}
                </Text>
                <Text style={styles.sectionCount}>{item.items.length}</Text>
              </View>
            );
          }
          return <UDRow item={item.item} />;
        }}
        refreshing={isRefetching}
        onRefresh={() => refetch()}
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
  statsBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    backgroundColor: theme.colors.bgSecondary,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
  },
  statsText: {
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.xs,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: theme.colors.bgSecondary,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
    borderLeftWidth: 3,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
  },
  sectionTitle: {
    fontSize: theme.fontSize.sm,
    fontWeight: 'bold',
    letterSpacing: 1,
  },
  sectionCount: {
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.xs,
  },
  row: {
    backgroundColor: theme.colors.bgElevated,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
  },
  rowHeader: {
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
  firm: {
    color: theme.colors.textPrimary,
    fontSize: theme.fontSize.md,
    marginBottom: 2,
  },
  action: {
    color: theme.colors.textSecondary,
    fontSize: theme.fontSize.sm,
    marginBottom: theme.spacing.xs,
  },
  ratings: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: theme.spacing.md,
    marginBottom: 2,
  },
  ratingLabel: {
    color: theme.colors.textSecondary,
    fontSize: theme.fontSize.sm,
  },
  pt: {
    color: theme.colors.accentGold,
    fontSize: theme.fontSize.sm,
    fontWeight: '600',
  },
  source: {
    color: theme.colors.textDim,
    fontSize: theme.fontSize.xs,
  },
});
