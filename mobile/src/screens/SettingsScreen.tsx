import React from 'react';
import {
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { theme } from '../theme';
import { useAppStore } from '../store';

const TIMEZONES = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Anchorage',
  'Pacific/Honolulu',
  'Europe/London',
  'Europe/Berlin',
  'Asia/Tokyo',
  'Asia/Shanghai',
  'Asia/Kolkata',
  'Australia/Sydney',
];

export default function SettingsScreen() {
  const timezone = useAppStore((s) => s.timezone);
  const setTimezone = useAppStore((s) => s.setTimezone);
  const apiBaseUrl = useAppStore((s) => s.apiBaseUrl);
  const setApiBaseUrl = useAppStore((s) => s.setApiBaseUrl);

  return (
    <ScrollView style={styles.container}>
      <Text style={styles.sectionTitle}>Timezone</Text>
      <View style={styles.timezoneList}>
        {TIMEZONES.map((tz) => (
          <TouchableOpacity
            key={tz}
            style={[
              styles.tzRow,
              timezone === tz && styles.tzRowActive,
            ]}
            onPress={() => setTimezone(tz)}
          >
            <Text
              style={[
                styles.tzText,
                timezone === tz && styles.tzTextActive,
              ]}
            >
              {tz}
            </Text>
            {timezone === tz && (
              <Text style={styles.checkmark}>{'\u2713'}</Text>
            )}
          </TouchableOpacity>
        ))}
      </View>

      <Text style={styles.sectionTitle}>API Base URL</Text>
      <TextInput
        style={styles.input}
        value={apiBaseUrl}
        onChangeText={setApiBaseUrl}
        placeholder="http://localhost:8000"
        placeholderTextColor={theme.colors.textMuted}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
      />

      <Text style={styles.sectionTitle}>About</Text>
      <View style={styles.aboutSection}>
        <Text style={styles.aboutLabel}>App</Text>
        <Text style={styles.aboutValue}>NewsAgent Mobile</Text>
        <Text style={styles.aboutLabel}>Version</Text>
        <Text style={styles.aboutValue}>1.0.0</Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.colors.bgPrimary,
  },
  sectionTitle: {
    color: theme.colors.textSecondary,
    fontSize: theme.fontSize.sm,
    fontWeight: '600',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    paddingHorizontal: theme.spacing.lg,
    paddingTop: theme.spacing.xl,
    paddingBottom: theme.spacing.sm,
  },
  timezoneList: {
    backgroundColor: theme.colors.bgElevated,
    borderTopWidth: 1,
    borderBottomWidth: 1,
    borderColor: theme.colors.borderSubtle,
  },
  tzRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderSubtle,
  },
  tzRowActive: {
    backgroundColor: theme.colors.accentBlue + '11',
  },
  tzText: {
    color: theme.colors.textPrimary,
    fontSize: theme.fontSize.md,
  },
  tzTextActive: {
    color: theme.colors.accentBlue,
    fontWeight: '600',
  },
  checkmark: {
    color: theme.colors.accentBlue,
    fontSize: theme.fontSize.lg,
    fontWeight: 'bold',
  },
  input: {
    backgroundColor: theme.colors.bgElevated,
    color: theme.colors.textPrimary,
    fontSize: theme.fontSize.md,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
    borderTopWidth: 1,
    borderBottomWidth: 1,
    borderColor: theme.colors.borderSubtle,
  },
  aboutSection: {
    backgroundColor: theme.colors.bgElevated,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
    borderTopWidth: 1,
    borderBottomWidth: 1,
    borderColor: theme.colors.borderSubtle,
  },
  aboutLabel: {
    color: theme.colors.textMuted,
    fontSize: theme.fontSize.xs,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginTop: theme.spacing.sm,
  },
  aboutValue: {
    color: theme.colors.textPrimary,
    fontSize: theme.fontSize.md,
    marginBottom: theme.spacing.sm,
  },
});
