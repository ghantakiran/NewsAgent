import React, { useMemo, useState } from 'react';
import {
  FlatList,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { theme } from '../theme';
import useAlertsWebSocket from '../hooks/useAlertsWebSocket';
import AlertCard from '../components/AlertCard';
import PulseIndicator from '../components/PulseIndicator';

export default function LiveAlertsScreen() {
  const [filter, setFilter] = useState('');

  // Parse the comma/space-separated filter into a stable uppercase ticker list.
  const tickers = useMemo(
    () =>
      filter
        .toUpperCase()
        .split(/[,\s]+/)
        .map((t) => t.trim())
        .filter(Boolean),
    [filter]
  );

  const { groups, connected } = useAlertsWebSocket(tickers);

  return (
    <View style={styles.container}>
      <TextInput
        style={styles.searchBar}
        placeholder="Filter tickers e.g. AAPL, NVDA"
        placeholderTextColor={theme.colors.textMuted}
        value={filter}
        onChangeText={setFilter}
        autoCapitalize="characters"
        autoCorrect={false}
      />

      <View style={styles.statusBar}>
        <PulseIndicator
          color={connected ? theme.colors.accentGreen : theme.colors.textMuted}
        />
        <Text style={styles.statusText}>
          {connected ? 'LIVE' : 'connecting…'}
        </Text>
        <Text style={styles.countText}>
          {groups.length} {groups.length === 1 ? 'alert' : 'alerts'}
        </Text>
      </View>

      <FlatList
        data={groups}
        keyExtractor={(item) => item.group_id}
        renderItem={({ item }) => <AlertCard group={item} />}
        contentContainerStyle={
          groups.length === 0 ? styles.empty : styles.listContent
        }
        ListEmptyComponent={
          <Text style={styles.emptyText}>
            {connected ? 'Waiting for alerts…' : 'Connecting to live stream…'}
          </Text>
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
  statusBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: theme.spacing.sm,
    backgroundColor: theme.colors.bgSecondary,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
  },
  statusText: {
    color: theme.colors.textSecondary,
    fontSize: theme.fontSize.xs,
    fontWeight: '600',
    letterSpacing: 0.5,
  },
  countText: {
    marginLeft: 'auto',
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.xs,
  },
  listContent: {
    padding: theme.spacing.md,
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
