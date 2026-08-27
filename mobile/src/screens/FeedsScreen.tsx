import React, { useState } from 'react';
import {
  FlatList,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { theme } from '../theme';
import { useFeeds } from '../hooks/useApi';
import { Feed } from '../types';

function FeedRow({ feed }: { feed: Feed }) {
  const [enabled, setEnabled] = useState(feed.enabled);
  const statusIcon = feed.error ? '\uD83D\uDD34' : feed.enabled ? '\uD83D\uDFE2' : '\u26AA';

  return (
    <View style={styles.feedRow}>
      <View style={styles.feedInfo}>
        <View style={styles.feedNameRow}>
          <Text style={styles.statusIcon}>{statusIcon}</Text>
          <Text style={styles.feedName}>{feed.name}</Text>
        </View>
        <Text style={styles.feedUrl} numberOfLines={1}>
          {feed.url}
        </Text>
        <Text style={styles.feedCategory}>{feed.category.toUpperCase()}</Text>
      </View>
      {feed.is_custom && (
        <Switch
          value={enabled}
          onValueChange={setEnabled}
          trackColor={{
            false: theme.colors.bgHover,
            true: theme.colors.accentBlue + '66',
          }}
          thumbColor={enabled ? theme.colors.accentBlue : theme.colors.textMuted}
        />
      )}
    </View>
  );
}

export default function FeedsScreen() {
  const { data, isLoading, refetch, isRefetching } = useFeeds();
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState('');
  const [newUrl, setNewUrl] = useState('');
  const [newCategory, setNewCategory] = useState('');

  const feeds = data?.feeds ?? [];

  return (
    <View style={styles.container}>
      <FlatList
        data={feeds}
        keyExtractor={(item, index) => `${item.url}-${index}`}
        renderItem={({ item }) => <FeedRow feed={item} />}
        refreshing={isRefetching}
        onRefresh={() => refetch()}
        contentContainerStyle={feeds.length === 0 ? styles.empty : undefined}
        ListEmptyComponent={
          !isLoading ? (
            <Text style={styles.emptyText}>No feeds configured</Text>
          ) : null
        }
        ListFooterComponent={
          <View style={styles.footer}>
            {showAdd ? (
              <View style={styles.addForm}>
                <TextInput
                  style={styles.input}
                  placeholder="Feed name"
                  placeholderTextColor={theme.colors.textMuted}
                  value={newName}
                  onChangeText={setNewName}
                />
                <TextInput
                  style={styles.input}
                  placeholder="Feed URL"
                  placeholderTextColor={theme.colors.textMuted}
                  value={newUrl}
                  onChangeText={setNewUrl}
                  autoCapitalize="none"
                  keyboardType="url"
                />
                <TextInput
                  style={styles.input}
                  placeholder="Category"
                  placeholderTextColor={theme.colors.textMuted}
                  value={newCategory}
                  onChangeText={setNewCategory}
                  autoCapitalize="none"
                />
              </View>
            ) : null}
            <TouchableOpacity
              style={styles.addButton}
              onPress={() => setShowAdd(!showAdd)}
            >
              <Text style={styles.addButtonText}>
                {showAdd ? 'Cancel' : 'Add Custom Feed'}
              </Text>
            </TouchableOpacity>
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
  feedRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: theme.colors.bgElevated,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
  },
  feedInfo: {
    flex: 1,
    marginRight: theme.spacing.md,
  },
  feedNameRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: theme.spacing.sm,
    marginBottom: 2,
  },
  statusIcon: {
    fontSize: theme.fontSize.xs,
  },
  feedName: {
    color: theme.colors.textPrimary,
    fontSize: theme.fontSize.md,
    fontWeight: '600',
  },
  feedUrl: {
    color: theme.colors.textDim,
    fontSize: theme.fontSize.xs,
    marginBottom: 2,
  },
  feedCategory: {
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.xs,
    fontWeight: '600',
    letterSpacing: 0.5,
  },
  footer: {
    padding: theme.spacing.lg,
  },
  addForm: {
    marginBottom: theme.spacing.md,
    gap: theme.spacing.sm,
  },
  input: {
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
    backgroundColor: theme.colors.accentBlue + '22',
    borderWidth: 1,
    borderColor: theme.colors.accentBlue,
    borderRadius: theme.borderRadius.md,
    paddingVertical: theme.spacing.md,
    alignItems: 'center',
  },
  addButtonText: {
    color: theme.colors.accentBlue,
    fontSize: theme.fontSize.md,
    fontWeight: '600',
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
