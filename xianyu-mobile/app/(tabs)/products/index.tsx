import { Text, useColorScheme } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, spacing, typography } from '@/lib/theme';
import ItemsScreen from '../mine/items';

/** Share the management screen without changing the selected tab. */
export default function ProductsPage() {
  const scheme = useColorScheme();
  const c = colors[scheme === 'dark' ? 'dark' : 'light'];
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: c.background }} edges={['top']}>
      <Text style={{ ...typography.heading, color: c.text, padding: spacing.lg }}>商品管理</Text>
      <ItemsScreen />
    </SafeAreaView>
  );
}
