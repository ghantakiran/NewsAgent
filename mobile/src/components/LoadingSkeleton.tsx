import React, { useEffect, useRef } from 'react';
import { Animated, StyleSheet, View } from 'react-native';
import { theme } from '../theme';

interface Props {
  width?: number | string;
  height?: number;
  borderRadius?: number;
  style?: any;
}

export function LoadingSkeleton({ width = '100%', height = 16, borderRadius = 4, style }: Props) {
  const animatedValue = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(animatedValue, { toValue: 1, duration: 1000, useNativeDriver: true }),
        Animated.timing(animatedValue, { toValue: 0, duration: 1000, useNativeDriver: true }),
      ])
    );
    animation.start();
    return () => animation.stop();
  }, []);

  const opacity = animatedValue.interpolate({
    inputRange: [0, 1],
    outputRange: [0.3, 0.7],
  });

  return (
    <Animated.View
      style={[
        { width: width as any, height, borderRadius, backgroundColor: theme.colors.borderSubtle, opacity },
        style,
      ]}
    />
  );
}

export function ArticleCardSkeleton() {
  return (
    <View style={styles.card}>
      <LoadingSkeleton width={44} height={14} />
      <View style={styles.cardContent}>
        <View style={styles.cardBadges}>
          <LoadingSkeleton width={40} height={18} borderRadius={4} />
          <LoadingSkeleton width={40} height={18} borderRadius={4} />
        </View>
        <LoadingSkeleton width="90%" height={14} style={{ marginTop: 6 }} />
        <LoadingSkeleton width="60%" height={14} style={{ marginTop: 4 }} />
      </View>
    </View>
  );
}

export function UDRowSkeleton() {
  return (
    <View style={styles.udRow}>
      <LoadingSkeleton width={50} height={18} />
      <LoadingSkeleton width={80} height={14} />
      <LoadingSkeleton width={60} height={14} />
    </View>
  );
}

export function EarningsCardSkeleton() {
  return (
    <View style={styles.earningsCard}>
      <View style={styles.cardBadges}>
        <LoadingSkeleton width={50} height={20} />
        <LoadingSkeleton width={60} height={14} />
      </View>
      <LoadingSkeleton width="80%" height={14} style={{ marginTop: 8 }} />
      <View style={[styles.cardBadges, { marginTop: 8 }]}>
        <LoadingSkeleton width={60} height={20} borderRadius={4} />
        <LoadingSkeleton width={60} height={20} borderRadius={4} />
        <LoadingSkeleton width={50} height={20} borderRadius={12} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    padding: 12,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
    gap: 10,
  },
  cardContent: { flex: 1 },
  cardBadges: { flexDirection: 'row', gap: 6 },
  udRow: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 10,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
    gap: 12,
  },
  earningsCard: {
    padding: 14,
    borderWidth: 1,
    borderColor: theme.colors.borderSubtle,
    borderRadius: theme.borderRadius.lg,
    backgroundColor: theme.colors.bgElevated,
    marginBottom: 8,
  },
});
