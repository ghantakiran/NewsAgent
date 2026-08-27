import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View, ScrollView } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { theme } from '../theme';
import type { MoreStackParamList } from '../navigation';

type NavProp = NativeStackNavigationProp<MoreStackParamList>;

interface MenuItem {
  label: string;
  screen: keyof MoreStackParamList;
}

const MENU_ITEMS: MenuItem[] = [
  { label: 'All News', screen: 'AllNews' },
  { label: 'By Symbol', screen: 'BySymbol' },
  { label: 'RSS Feeds', screen: 'Feeds' },
  { label: 'Watchlist', screen: 'Watchlist' },
  { label: 'Settings', screen: 'Settings' },
  { label: 'Login', screen: 'Login' },
];

export default function MoreScreen() {
  const navigation = useNavigation<NavProp>();

  return (
    <ScrollView style={styles.container}>
      {MENU_ITEMS.map((item) => (
        <TouchableOpacity
          key={item.screen}
          style={styles.row}
          onPress={() => navigation.navigate(item.screen)}
          activeOpacity={0.6}
        >
          <Text style={styles.label}>{item.label}</Text>
          <Text style={styles.chevron}>{'>'}</Text>
        </TouchableOpacity>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.colors.bgPrimary,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: theme.colors.bgElevated,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
  },
  label: {
    color: theme.colors.textPrimary,
    fontSize: theme.fontSize.lg,
  },
  chevron: {
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.lg,
  },
});
