import React from 'react';
import { Text } from 'react-native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { theme } from '../theme';

import LiveFeedScreen from '../screens/LiveFeedScreen';
import LiveAlertsScreen from '../screens/LiveAlertsScreen';
import UDRatingsScreen from '../screens/UDRatingsScreen';
import EarningsScreen from '../screens/EarningsScreen';
import CatalystsScreen from '../screens/CatalystsScreen';
import MoreScreen from '../screens/MoreScreen';
import BySymbolScreen from '../screens/BySymbolScreen';
import FeedsScreen from '../screens/FeedsScreen';
import WatchlistScreen from '../screens/WatchlistScreen';
import SettingsScreen from '../screens/SettingsScreen';
import AllNewsScreen from '../screens/AllNewsScreen';
import LoginScreen from '../screens/LoginScreen';

export type MoreStackParamList = {
  MoreMenu: undefined;
  BySymbol: undefined;
  AllNews: undefined;
  Feeds: undefined;
  Watchlist: undefined;
  Settings: undefined;
  Login: undefined;
};

const MoreStack = createNativeStackNavigator<MoreStackParamList>();

function MoreStackNavigator() {
  return (
    <MoreStack.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: theme.colors.bgSecondary },
        headerTintColor: theme.colors.textPrimary,
        headerTitleStyle: { fontWeight: '600' },
      }}
    >
      <MoreStack.Screen
        name="MoreMenu"
        component={MoreScreen}
        options={{ title: 'More' }}
      />
      <MoreStack.Screen
        name="BySymbol"
        component={BySymbolScreen}
        options={{ title: 'By Symbol' }}
      />
      <MoreStack.Screen
        name="AllNews"
        component={AllNewsScreen}
        options={{ title: 'All News' }}
      />
      <MoreStack.Screen
        name="Feeds"
        component={FeedsScreen}
        options={{ title: 'RSS Feeds' }}
      />
      <MoreStack.Screen
        name="Watchlist"
        component={WatchlistScreen}
        options={{ title: 'Watchlist' }}
      />
      <MoreStack.Screen
        name="Settings"
        component={SettingsScreen}
        options={{ title: 'Settings' }}
      />
      <MoreStack.Screen
        name="Login"
        component={LoginScreen}
        options={{ title: 'Login' }}
      />
    </MoreStack.Navigator>
  );
}

const Tab = createBottomTabNavigator();

export function AppNavigator() {
  return (
    <Tab.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: theme.colors.bgSecondary },
        headerTintColor: theme.colors.textPrimary,
        headerTitleStyle: { fontWeight: '600' },
        tabBarStyle: {
          backgroundColor: '#0c0d10',
          borderTopColor: theme.colors.borderSubtle,
        },
        tabBarActiveTintColor: '#0ea5e9',
        tabBarInactiveTintColor: '#5c6375',
        tabBarLabelStyle: { fontSize: 10 },
      }}
    >
      <Tab.Screen
        name="LiveFeed"
        component={LiveFeedScreen}
        options={{
          title: 'Live Feed',
          tabBarIcon: () => <Text style={{ fontSize: 18 }}>{'📰'}</Text>,
        }}
      />
      <Tab.Screen
        name="Ratings"
        component={UDRatingsScreen}
        options={{
          title: 'Ratings',
          tabBarIcon: () => <Text style={{ fontSize: 18 }}>{'📊'}</Text>,
        }}
      />
      <Tab.Screen
        name="Earnings"
        component={EarningsScreen}
        options={{
          title: 'Earnings',
          tabBarIcon: () => <Text style={{ fontSize: 18 }}>{'💰'}</Text>,
        }}
      />
      <Tab.Screen
        name="Catalysts"
        component={CatalystsScreen}
        options={{
          title: 'Catalysts',
          tabBarIcon: () => <Text style={{ fontSize: 18 }}>{'⚡'}</Text>,
        }}
      />
      <Tab.Screen
        name="Alerts"
        component={LiveAlertsScreen}
        options={{
          title: 'Live Alerts',
          tabBarIcon: () => <Text style={{ fontSize: 18 }}>{'🔔'}</Text>,
        }}
      />
      <Tab.Screen
        name="More"
        component={MoreStackNavigator}
        options={{
          title: 'More',
          headerShown: false,
          tabBarIcon: () => (
            <Text style={{ fontSize: 18, color: theme.colors.textMuted }}>
              {'☰'}
            </Text>
          ),
        }}
      />
    </Tab.Navigator>
  );
}
