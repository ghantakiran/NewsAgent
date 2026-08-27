import React, { useState } from 'react';
import {
  FlatList,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { theme } from '../theme';
import { useAppStore } from '../store';

export default function WatchlistScreen() {
  const [input, setInput] = useState('');
  const watchlist = useAppStore((s) => s.watchlist);
  const addTicker = useAppStore((s) => s.addTicker);
  const removeTicker = useAppStore((s) => s.removeTicker);

  const handleAdd = () => {
    const ticker = input.trim().toUpperCase();
    if (ticker && !watchlist.includes(ticker)) {
      addTicker(ticker);
      setInput('');
    }
  };

  return (
    <View style={styles.container}>
      <View style={styles.addRow}>
        <TextInput
          style={styles.input}
          placeholder="Enter ticker..."
          placeholderTextColor={theme.colors.textMuted}
          value={input}
          onChangeText={setInput}
          autoCapitalize="characters"
          autoCorrect={false}
          onSubmitEditing={handleAdd}
        />
        <TouchableOpacity style={styles.addButton} onPress={handleAdd}>
          <Text style={styles.addButtonText}>Add</Text>
        </TouchableOpacity>
      </View>

      <FlatList
        data={watchlist}
        keyExtractor={(item) => item}
        numColumns={3}
        columnWrapperStyle={styles.badgeRow}
        contentContainerStyle={styles.listContent}
        renderItem={({ item }) => (
          <View style={styles.badge}>
            <Text style={styles.badgeText}>{item}</Text>
            <TouchableOpacity
              onPress={() => removeTicker(item)}
              hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
            >
              <Text style={styles.removeText}>X</Text>
            </TouchableOpacity>
          </View>
        )}
        ListEmptyComponent={
          <View style={styles.empty}>
            <Text style={styles.emptyText}>No tickers in watchlist</Text>
            <Text style={styles.emptySubtext}>
              Add tickers above to get started
            </Text>
          </View>
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
  addRow: {
    flexDirection: 'row',
    padding: theme.spacing.lg,
    gap: theme.spacing.sm,
    backgroundColor: theme.colors.bgSecondary,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
  },
  input: {
    flex: 1,
    backgroundColor: theme.colors.bgElevated,
    color: theme.colors.textPrimary,
    fontSize: theme.fontSize.md,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.md,
    borderRadius: theme.borderRadius.md,
    borderWidth: 1,
    borderColor: theme.colors.borderMedium,
  },
  addButton: {
    backgroundColor: theme.colors.accentBlue,
    borderRadius: theme.borderRadius.md,
    paddingHorizontal: theme.spacing.xl,
    justifyContent: 'center',
  },
  addButtonText: {
    color: '#ffffff',
    fontSize: theme.fontSize.md,
    fontWeight: 'bold',
  },
  listContent: {
    padding: theme.spacing.lg,
  },
  badgeRow: {
    gap: theme.spacing.sm,
    marginBottom: theme.spacing.sm,
  },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: theme.spacing.sm,
    backgroundColor: theme.colors.accentBlue + '22',
    borderColor: theme.colors.accentBlue,
    borderWidth: 1,
    borderRadius: theme.borderRadius.lg,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
  },
  badgeText: {
    color: theme.colors.accentBlue,
    fontSize: theme.fontSize.lg,
    fontWeight: 'bold',
    fontFamily: 'Courier',
  },
  removeText: {
    color: theme.colors.accentRed,
    fontSize: theme.fontSize.sm,
    fontWeight: 'bold',
  },
  empty: {
    alignItems: 'center',
    paddingTop: theme.spacing.xl * 2,
  },
  emptyText: {
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.lg,
    marginBottom: theme.spacing.sm,
  },
  emptySubtext: {
    color: theme.colors.textDim,
    fontSize: theme.fontSize.sm,
  },
});
