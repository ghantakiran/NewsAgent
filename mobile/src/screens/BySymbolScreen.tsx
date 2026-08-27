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
import { useTickers, useArticles } from '../hooks/useApi';
import ArticleCard from '../components/ArticleCard';

function TickerSection({ ticker }: { ticker: string }) {
  const [expanded, setExpanded] = useState(false);
  const { data } = useArticles({ ticker, limit: 20 });
  const articles = data?.articles ?? [];

  return (
    <View>
      <TouchableOpacity
        style={styles.sectionHeader}
        onPress={() => setExpanded(!expanded)}
        activeOpacity={0.7}
      >
        <Text style={styles.sectionTicker}>{ticker}</Text>
        <Text style={styles.sectionCount}>
          {articles.length} articles {expanded ? '\u25B2' : '\u25BC'}
        </Text>
      </TouchableOpacity>
      {expanded &&
        articles.map((article) => (
          <ArticleCard key={article.id} article={article} />
        ))}
    </View>
  );
}

export default function BySymbolScreen() {
  const [search, setSearch] = useState('');
  const { data: tickerData } = useTickers();

  const allTickers = tickerData?.tickers ?? [];
  const filtered = search
    ? allTickers.filter((t) =>
        t.toLowerCase().includes(search.toLowerCase())
      )
    : allTickers;

  return (
    <View style={styles.container}>
      <TextInput
        style={styles.searchBar}
        placeholder="Search ticker..."
        placeholderTextColor={theme.colors.textMuted}
        value={search}
        onChangeText={setSearch}
        autoCapitalize="characters"
        autoCorrect={false}
      />

      <FlatList
        data={filtered.slice(0, 50)}
        keyExtractor={(item) => item}
        renderItem={({ item }) => <TickerSection ticker={item} />}
        contentContainerStyle={
          filtered.length === 0 ? styles.empty : undefined
        }
        ListEmptyComponent={
          <Text style={styles.emptyText}>No tickers found</Text>
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
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: theme.colors.bgSecondary,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
    borderLeftWidth: 3,
    borderLeftColor: theme.colors.accentBlue,
  },
  sectionTicker: {
    color: theme.colors.accentBlue,
    fontSize: theme.fontSize.lg,
    fontWeight: 'bold',
    fontFamily: 'Courier',
  },
  sectionCount: {
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.sm,
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
