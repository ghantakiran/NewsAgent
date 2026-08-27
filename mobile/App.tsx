import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { NavigationContainer, DefaultTheme } from '@react-navigation/native';
import { StatusBar } from 'expo-status-bar';
import { AppNavigator } from './src/navigation';
import { useNotifications } from './src/hooks/useNotifications';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 10000 },
  },
});

const navTheme = {
  ...DefaultTheme,
  dark: true,
  colors: {
    ...DefaultTheme.colors,
    primary: '#0ea5e9',
    background: '#07080a',
    card: '#0c0d10',
    text: '#e8eaf0',
    border: '#1c1e26',
    notification: '#ff3b4e',
  },
};

function AppContent() {
  useNotifications();
  return <AppNavigator />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <NavigationContainer theme={navTheme}>
        <StatusBar style="light" />
        <AppContent />
      </NavigationContainer>
    </QueryClientProvider>
  );
}
