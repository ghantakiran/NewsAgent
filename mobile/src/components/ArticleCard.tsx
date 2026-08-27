import React from 'react';
import { Linking, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { theme } from '../theme';
import { Article } from '../types';
import { relativeTime, formatTime } from '../utils';
import TickerBadge from './TickerBadge';
import CategoryBadge from './CategoryBadge';

interface ArticleCardProps {
  article: Article;
}

export default function ArticleCard({ article }: ArticleCardProps) {
  const handlePress = () => {
    Linking.openURL(article.url);
  };

  return (
    <View style={styles.card}>
      <View style={styles.topRow}>
        <Text style={styles.time}>{formatTime(article.published)}</Text>
        <View style={styles.relBadge}>
          <Text style={styles.relText}>{relativeTime(article.published)}</Text>
        </View>
        <View style={styles.tickers}>
          {article.tickers.slice(0, 3).map((t) => (
            <TickerBadge key={t} ticker={t} />
          ))}
        </View>
      </View>

      <TouchableOpacity onPress={handlePress} activeOpacity={0.7}>
        <Text style={styles.title} numberOfLines={2}>
          {article.title}
        </Text>
      </TouchableOpacity>

      <View style={styles.bottomRow}>
        <CategoryBadge category={article.category} />
        <View style={styles.sourceBadge}>
          <Text style={styles.sourceText}>{article.source}</Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: theme.colors.bgElevated,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
  },
  topRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: theme.spacing.xs,
  },
  time: {
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.xs,
    fontFamily: 'Courier',
    marginRight: theme.spacing.sm,
  },
  relBadge: {
    backgroundColor: theme.colors.bgHover,
    borderRadius: theme.borderRadius.sm,
    paddingHorizontal: theme.spacing.xs,
    paddingVertical: 1,
    marginRight: theme.spacing.sm,
  },
  relText: {
    color: theme.colors.textSecondary,
    fontSize: theme.fontSize.xs,
  },
  tickers: {
    flexDirection: 'row',
    flex: 1,
  },
  title: {
    color: theme.colors.textPrimary,
    fontSize: theme.fontSize.md,
    lineHeight: 20,
    marginBottom: theme.spacing.xs,
  },
  bottomRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: theme.spacing.sm,
  },
  sourceBadge: {
    backgroundColor: theme.colors.bgHover,
    borderRadius: theme.borderRadius.sm,
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 2,
  },
  sourceText: {
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.xs,
  },
});
