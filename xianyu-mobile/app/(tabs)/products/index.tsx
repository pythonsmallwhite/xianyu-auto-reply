import { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  Alert,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useColorScheme } from 'react-native';
import { Card, EmptyState, Loading, Button, Input, FormModal, StatCard } from '@/components/ui';
import { ShoppingBag, ClipboardList, Activity, Package } from 'lucide-react-native';
import { useRouter } from 'expo-router';
import { colors, spacing, typography, radius } from '@/lib/theme';
import {
  getListingOverview,
  getMonitoredItems,
  type ListingOverview,
  type MonitoredItem,
} from '@/api/wrappers/products';
import { updateItemPrice } from '@/api/wrappers/item-edit';

type Palette = typeof colors.light;

/** 根据监控状态文案返回主题色 */
function statusColor(status: string, c: Palette): string {
  if (status.includes('已下单')) return c.success;
  if (status.includes('失败')) return c.error;
  if (status.includes('私信')) return c.primary;
  return c.textMuted;
}

export default function ProductsPage() {
  const scheme = useColorScheme();
  const c = colors[scheme === 'dark' ? 'dark' : 'light'];

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: c.background }]}>
      <MonitorTab />
    </SafeAreaView>
  );
}

// ---------------------------------------------------------------------------
// 商品监控：概览统计 + 监控商品列表
// ---------------------------------------------------------------------------

function MonitorTab() {
  const scheme = useColorScheme();
  const c = colors[scheme === 'dark' ? 'dark' : 'light'];
  const router = useRouter();
  const [overview, setOverview] = useState<ListingOverview | null>(null);
  const [items, setItems] = useState<MonitoredItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  // 改价 Modal：priceTarget 为当前改价商品，null 表示 Modal 关闭
  const [priceTarget, setPriceTarget] = useState<MonitoredItem | null>(null);
  const [priceText, setPriceText] = useState('');
  const [quantityText, setQuantityText] = useState('');
  const [savingPrice, setSavingPrice] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const [ov, list] = await Promise.all([
        getListingOverview(),
        getMonitoredItems(),
      ]);
      setOverview(ov);
      setItems(list);
    } catch (e) {
      Alert.alert('加载失败', (e as Error).message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function openPriceModal(item: MonitoredItem) {
    if (!item.cookie_id) {
      Alert.alert('无法改价', '该商品未关联账号信息，无法改价');
      return;
    }
    setPriceTarget(item);
    setPriceText(item.price);
    setQuantityText('');
  }

  function closePriceModal() {
    setPriceTarget(null);
  }

  async function submitPrice() {
    const target = priceTarget;
    if (!target || !target.cookie_id) return;
    const price = Number(priceText);
    if (!Number.isFinite(price) || price <= 0) {
      Alert.alert('提示', '请输入有效的价格');
      return;
    }
    const quantityRaw = quantityText.trim();
    if (!quantityRaw) {
      Alert.alert('提示', '请输入库存数量');
      return;
    }
    const quantity = Number(quantityRaw);
    if (!Number.isInteger(quantity) || quantity < 0) {
      Alert.alert('提示', '请输入有效的库存数量');
      return;
    }
    setSavingPrice(true);
    try {
      const res = await updateItemPrice(target.cookie_id, target.item_id, {
        price,
        quantity,
      });
      if (!res.success) {
        Alert.alert('改价失败', res.message || '请稍后重试');
        return;
      }
      closePriceModal();
      await load();
      Alert.alert('改价成功', res.message || '价格与库存已更新');
    } catch (e) {
      Alert.alert('改价失败', (e as Error).message);
    } finally {
      setSavingPrice(false);
    }
  }

  if (loading) return <Loading label="加载监控数据..." />;

  return (
    <>
      <FlatList
        data={items}
        keyExtractor={(item) => item.item_id}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={load} />
        }
        ListHeaderComponent={
          <View style={styles.statsRow}>
            <StatCard
              label="任务数"
              value={overview?.total_tasks ?? 0}
              icon={ClipboardList}
              onPress={() => router.push('/(tabs)/mine/listing-monitor')}
            />
            <StatCard
              label="活跃任务"
              value={overview?.active_tasks ?? 0}
              icon={Activity}
              accent={c.success}
              onPress={() => router.push('/(tabs)/mine/listing-monitor')}
            />
            <StatCard
              label="商品数"
              value={overview?.total_items ?? 0}
              icon={Package}
              onPress={() => router.push('/(tabs)/mine/listing-monitor')}
            />
          </View>
        }
        renderItem={({ item }) => (
          <Card style={styles.itemCard}>
            <View style={styles.itemHeader}>
              <Text
                style={[styles.itemTitle, { color: c.text }]}
                numberOfLines={2}
              >
                {item.title || '未命名商品'}
              </Text>
              <Text style={[styles.itemPrice, { color: c.primary }]}>
                ¥{item.price}
              </Text>
            </View>
            <View style={[styles.itemFooter, { borderTopColor: c.border }]}>
              <Text
                style={[styles.itemId, { color: c.textMuted }]}
                numberOfLines={1}
              >
                ID: {item.item_id}
              </Text>
              <Text
                style={[styles.itemStatus, { color: statusColor(item.status, c) }]}
              >
                {item.status}
              </Text>
            </View>
            <View style={styles.itemActions}>
              <Button
                label="改价"
                variant="secondary"
                onPress={() => openPriceModal(item)}
                style={styles.actionBtn}
              />
            </View>
          </Card>
        )}
        ListEmptyComponent={
          <EmptyState
            icon={ShoppingBag}
            title="暂无监控商品"
            message="添加监控后商品状态会显示在这里"
            actionLabel="添加监控商品"
            onAction={() => router.push('/(tabs)/mine/listing-monitor')}
          />
        }
        contentContainerStyle={styles.listContent}
      />

      {/* 改价 Modal */}
      <FormModal
        visible={priceTarget !== null}
        onClose={closePriceModal}
        title="商品改价"
      >
        <Text
          style={[styles.priceItemTitle, { color: c.textMuted }]}
          numberOfLines={1}
        >
          {priceTarget?.title || '未命名商品'}
        </Text>

        <View style={styles.fieldGroup}>
          <Text style={[styles.fieldLabel, { color: c.textSecondary }]}>
            价格（元）
          </Text>
          <Input
            value={priceText}
            onChangeText={setPriceText}
            placeholder="请输入新价格"
            keyboardType="number-pad"
            autoFocus
          />
        </View>

        <View style={styles.fieldGroup}>
          <Text style={[styles.fieldLabel, { color: c.textSecondary }]}>
            库存
          </Text>
          <Input
            value={quantityText}
            onChangeText={setQuantityText}
            placeholder="请输入库存数量"
            keyboardType="number-pad"
          />
        </View>

        <View style={styles.modalActions}>
          <Button
            label="取消"
            variant="ghost"
            onPress={closePriceModal}
            style={styles.modalBtn}
          />
          <Button
            label="确定"
            onPress={submitPrice}
            loading={savingPrice}
            disabled={savingPrice}
            style={styles.modalBtn}
          />
        </View>
      </FormModal>
    </>
  );
}

// ---------------------------------------------------------------------------
// 样式
// ---------------------------------------------------------------------------

const styles = StyleSheet.create({
  container: { flex: 1 },
  // 通用列表
  listContent: { padding: spacing.lg, gap: spacing.md },
  empty: { alignItems: 'center', justifyContent: 'center', paddingVertical: 28 },
  emptyText: { ...typography.body },
  // 子页头
  subHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  subTitle: { ...typography.heading },
  // 监控统计
  statsRow: { flexDirection: 'row', gap: spacing.md, marginBottom: spacing.md },
  // 监控商品项
  itemCard: { gap: spacing.sm },
  itemHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: spacing.md,
  },
  itemTitle: { ...typography.body, flex: 1, fontWeight: '500' },
  itemPrice: { ...typography.body, fontWeight: '600' },
  itemFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderTopWidth: 1,
    paddingTop: spacing.sm,
    gap: spacing.sm,
  },
  itemId: { ...typography.small, flex: 1 },
  itemStatus: { ...typography.caption, fontWeight: '600' },
  itemActions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
  },
  actionBtn: { minHeight: 36, paddingHorizontal: spacing.lg },
  // Modal
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.lg,
  },
  modalCard: {
    width: '100%',
    maxWidth: 340,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.md,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  modalTitle: { ...typography.heading },
  closeBtn: { fontSize: 22, paddingHorizontal: spacing.xs },
  priceItemTitle: { ...typography.small },
  fieldGroup: { gap: spacing.xs },
  fieldLabel: { ...typography.caption },
  modalActions: { flexDirection: 'row', gap: spacing.sm },
  modalBtn: { flex: 1 },
});
