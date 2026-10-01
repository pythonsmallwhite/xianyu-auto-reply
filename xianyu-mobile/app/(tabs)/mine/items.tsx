import { useState, useCallback, useEffect, useRef } from 'react';
import {
  Alert,
  View,
  Text,
  StyleSheet,
  FlatList,
  RefreshControl,
  Pressable,
  ScrollView,
  Switch,
  Image,
  ActivityIndicator,
  useColorScheme,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Card, EmptyState, Badge, Loading, Button } from '@/components/ui';
import { Package, Ticket } from 'lucide-react-native';
import { colors, spacing, typography, radius } from '@/lib/theme';
import { getXianyuItems, type XianyuItem } from '@/api/wrappers/items';
import { batchDeleteItems } from '@/api/wrappers/item-edit';
import { getAccountOptions, type AccountOption } from '@/api/wrappers/accounts';
import { ItemCardRelationModal } from '@/components/card-relation/ItemCardRelationModal';

const PAGE_SIZE = 20;

export default function ItemsScreen() {
  const scheme = useColorScheme();
  const c = colors[scheme === 'dark' ? 'dark' : 'light'];
  const router = useRouter();

  const [accounts, setAccounts] = useState<AccountOption[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<string>('');
  const [showHistory, setShowHistory] = useState(false);
  const [batchSelectMode, setBatchSelectMode] = useState(false);
  const [batchSelectedItems, setBatchSelectedItems] = useState<XianyuItem[]>([]);
  const [items, setItems] = useState<XianyuItem[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [total, setTotal] = useState(0);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 关联卡券弹窗：当前正在关联卡券的商品，非空即表示弹窗打开
  const [relationItem, setRelationItem] = useState<XianyuItem | null>(null);

  // 筛选在事件中立即失效旧请求，序号同时保护响应、错误和加载状态。
  const reqSeqRef = useRef(0);
  const filtersRef = useRef({ accountId: '', showHistory: false });
  const requestPendingRef = useRef(false);

  const changeFilters = (accountId: string, history: boolean) => {
    if (accountId === filtersRef.current.accountId && history === filtersRef.current.showHistory) return;
    filtersRef.current = { accountId, showHistory: history };
    ++reqSeqRef.current;
    requestPendingRef.current = true;
    setItems([]);
    setPage(1);
    setTotalPages(0);
    setTotal(0);
    setError(null);
    setLoading(true);
    setRefreshing(false);
    setLoadingMore(false);
    setRelationItem(null);
    setSelectedAccountId(accountId);
    setShowHistory(history);
  };

  const loadAccounts = useCallback(async () => {
    try {
      const opts = await getAccountOptions();
      setAccounts(opts);
    } catch {
      // 账号加载失败不阻塞商品列表（仍可看"全部"）
    }
  }, []);

  const loadItems = useCallback(
    async (opts?: { append?: boolean; fromPage?: number }) => {
      const append = opts?.append ?? false;
      if (append && requestPendingRef.current) return;
      const targetPage = opts?.fromPage ?? 1;
      const { accountId, showHistory: history } = filtersRef.current;
      const seq = ++reqSeqRef.current;
      requestPendingRef.current = true;
      setLoadingMore(append);
      setRefreshing(!append);
      setError(null);
      try {
        const res = await getXianyuItems(targetPage, PAGE_SIZE, accountId || undefined, history);
        if (seq !== reqSeqRef.current) return;
        setItems((prev) => {
          if (seq !== reqSeqRef.current) return prev;
          // 刷新不沿用旧页；同一商品在不同账号下保留独立记录。
          const base = append ? prev : [];
          const seen = new Set(base.map((i) => JSON.stringify([i.cookie_id, i.item_id])));
          const newItems = res.items.filter((i) => {
            const key = JSON.stringify([i.cookie_id, i.item_id]);
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
          });
          return [...base, ...newItems];
        });
        setPage(res.page);
        setTotalPages(res.total_pages);
        setTotal(res.total);
      } catch (e) {
        if (seq !== reqSeqRef.current) return;
        setError((e as Error).message || '加载商品失败');
      } finally {
        if (seq !== reqSeqRef.current) return;
        requestPendingRef.current = false;
        setLoadingMore(false);
        setRefreshing(false);
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    loadAccounts();
  }, [loadAccounts]);

  useEffect(() => {
    setLoading(true);
    loadItems();
    return () => { ++reqSeqRef.current; };
  }, [selectedAccountId, showHistory, loadItems]);

  const handleRefresh = useCallback(() => {
    loadItems();
  }, [loadItems]);

  const handleLoadMore = useCallback(() => {
    if (loadingMore || refreshing || loading) return;
    if (totalPages === 0 || page >= totalPages) return;
    loadItems({ append: true, fromPage: page + 1 });
  }, [loadingMore, refreshing, loading, totalPages, page, loadItems]);

  const canOperate = useCallback((item: XianyuItem) => {
    if (!item.cookie_id || !item.item_id) return false;
    if (item.source_category !== 'managed' && item.source_category !== 'tool_published_unlinked' &&
        item.cookie_id !== filtersRef.current.accountId) {
      Alert.alert('请选择所属账号', '历史/来源待确认商品仅允许在所属账号下单件操作。');
      return false;
    }
    return true;
  }, []);

  const handleEdit = useCallback(
    (item: XianyuItem) => {
      if (!canOperate(item)) return;
      router.push({
        pathname: '/(tabs)/mine/item-edit',
        params: { cookieId: item.cookie_id, itemId: item.item_id },
      });
    },
    [router, canOperate],
  );

  const handleDelete = useCallback(
    (item: XianyuItem) => {
      if (!canOperate(item)) return;
      const filterSeq = reqSeqRef.current;
      Alert.alert(
        '删除商品',
        `确定删除「${item.title || '无标题'}」吗？此操作不可撤销。`,
        [
          { text: '取消', style: 'cancel' },
          {
            text: '删除',
            style: 'destructive',
            onPress: async () => {
              if (filterSeq !== reqSeqRef.current || !canOperate(item)) return;
              try {
                await batchDeleteItems(item.cookie_id, [item.item_id]);
                if (filterSeq === reqSeqRef.current) loadItems();
              } catch (e) {
                Alert.alert('删除失败', (e as Error).message || '未知错误');
              }
            },
          },
        ],
      );
    },
    [loadItems, canOperate],
  );

  const handleLongPress = useCallback(
    (item: XianyuItem) => {
      if (!canOperate(item)) return;
      Alert.alert(item.title || '无标题', undefined, [
        { text: '编辑', onPress: () => handleEdit(item) },
        { text: '删除', style: 'destructive', onPress: () => handleDelete(item) },
        { text: '取消', style: 'cancel' },
      ]);
    },
    [handleEdit, handleDelete, canOperate],
  );

  const toggleBatchItem = useCallback((item: XianyuItem) => {
    if (!item.cookie_id || (item.source_category !== 'managed' && item.source_category !== 'tool_published_unlinked')) {
      Alert.alert('无法批量编辑', '历史或来源待确认商品仅允许单件操作。');
      return;
    }
    setBatchSelectedItems((previous) => {
      const key = item.cookie_id + ':' + item.item_id;
      const has = previous.some((entry) => entry.cookie_id + ':' + entry.item_id === key);
      return has ? previous.filter((entry) => entry.cookie_id + ':' + entry.item_id !== key) : [...previous, item];
    });
  }, []);

  const openBatchEdit = useCallback(() => {
    if (!batchSelectedItems.length) {
      Alert.alert('提示', '请先选择商品');
      return;
    }
    const accountIds = new Set(batchSelectedItems.map((item) => item.cookie_id));
    if (accountIds.size !== 1) {
      Alert.alert('提示', '批量编辑必须选择同一账号的商品');
      return;
    }
    router.push({
      pathname: '/(tabs)/mine/item-edit',
      params: {
        cookieId: batchSelectedItems[0].cookie_id,
        itemIds: batchSelectedItems.map((item) => item.item_id).join(','),
      },
    });
    setBatchSelectMode(false);
    setBatchSelectedItems([]);
  }, [batchSelectedItems, router]);

  const accountLabel = (acc: AccountOption) => acc.remark || acc.id;

  const renderItem = ({ item }: { item: XianyuItem }) => (
    <Pressable
      onPress={() => batchSelectMode ? toggleBatchItem(item) : handleEdit(item)}
      onLongPress={() => batchSelectMode ? toggleBatchItem(item) : handleLongPress(item)}
      style={({ pressed }) => ({ opacity: pressed ? 0.6 : 1 })}
    >
      <Card style={[styles.card, batchSelectMode && batchSelectedItems.some((entry) => entry.cookie_id === item.cookie_id && entry.item_id === item.item_id) ? { borderColor: c.primary, borderWidth: 1 } : null]}>
        <View style={styles.cardRow}>
          {item.image ? (
            <Image
              source={{ uri: item.image }}
              style={[styles.thumb, { backgroundColor: c.surfaceAlt }]}
            />
          ) : (
            <View style={[styles.thumb, { backgroundColor: c.surfaceAlt }]}>
              <Package size={24} stroke={c.textMuted} />
            </View>
          )}
          <View style={styles.body}>
            <Text
              style={[styles.title, { color: c.text }]}
              numberOfLines={2}
            >
              {item.title || '无标题'}
            </Text>
            <Text style={[styles.qty, { color: c.textMuted }]}>
              {item.source_category === 'managed' ? '已关联内部商品' :
                item.source_category === 'tool_published_unlinked' ? '工具发布 · 未关联' : '历史/来源待确认'}
              {` · 账号 ${item.cookie_id || '待确认'}`}
            </Text>
            <View style={styles.metaRow}>
              <Text style={[styles.price, { color: c.warning }]} numberOfLines={1}>
                {item.price ? `¥${item.price}` : '价格未知'}
              </Text>
              {item.status ? (
                <Badge label={item.status} variant="info" />
              ) : null}
              {item.quantity !== null && item.quantity !== '' && item.quantity !== undefined ? (
                <Text style={[styles.qty, { color: c.textMuted }]} numberOfLines={1}>
                  库存 {item.quantity}
                </Text>
              ) : null}
            </View>
          </View>
        </View>
        {(item.source_category === 'managed' || item.source_category === 'tool_published_unlinked') && <Pressable
          onPress={() => { if (canOperate(item)) setRelationItem(item); }}
          style={({ pressed }) => [
            styles.actionRow,
            { borderColor: c.borderLight, opacity: pressed ? 0.6 : 1 },
          ]}
        >
          <Ticket size={14} stroke={c.primary} />
          <Text style={[styles.actionText, { color: c.primary }]}>关联卡券</Text>
        </Pressable>}
      </Card>
    </Pressable>
  );

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: c.background }]} edges={['left', 'right', 'bottom']}>
      <View style={styles.toolbar}>
        <Button label="关联商品延迟下架" onPress={() => router.push('/(tabs)/mine/offline-batches' as any)} />
        <Button label={batchSelectMode ? '取消选择' : '选择批量编辑'} variant="secondary" onPress={() => { setBatchSelectMode((value) => !value); setBatchSelectedItems([]); }} />
        {batchSelectMode && <Button label={'批量编辑 (' + batchSelectedItems.length + ')'} onPress={openBatchEdit} disabled={!batchSelectedItems.length} />}
      </View>
      {/* 账号选择（胶囊横滑） */}
      <View style={[styles.accountBar, { borderBottomColor: c.borderLight }]}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipRowScroll}>
          <Pressable
            onPress={() => changeFilters('', showHistory)}
            style={[
              styles.chip,
              {
                borderColor: selectedAccountId === '' ? c.primary : c.border,
                backgroundColor: selectedAccountId === '' ? c.primary : c.surface,
              },
            ]}
          >
            <Text style={[styles.chipText, { color: selectedAccountId === '' ? '#FFFFFF' : c.text }]}>
              全部
            </Text>
          </Pressable>
          {accounts.map((acc) => {
            const selected = selectedAccountId === acc.id;
            return (
              <Pressable
                key={acc.id}
                onPress={() => changeFilters(acc.id, showHistory)}
                style={[
                  styles.chip,
                  {
                    borderColor: selected ? c.primary : c.border,
                    backgroundColor: selected ? c.primary : c.surface,
                  },
                ]}
              >
                <Text style={[styles.chipText, { color: selected ? '#FFFFFF' : c.text }]} numberOfLines={1}>
                  {accountLabel(acc)}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>
        <Text style={[styles.countText, { color: c.textMuted }]}>
          共 {total} 件
        </Text>
      </View>

      <View style={styles.historyRow}>
        <Text style={[styles.qty, { color: c.text }]}>显示历史商品</Text>
        <Switch
          accessibilityLabel="显示历史商品"
          value={showHistory}
          onValueChange={(value) => changeFilters(selectedAccountId, value)}
        />
      </View>
      <FlatList
        data={items}
        keyExtractor={(item) => `${item.cookie_id}-${item.item_id}-${item.id}`}
        renderItem={renderItem}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
        contentContainerStyle={styles.list}
        onEndReached={handleLoadMore}
        onEndReachedThreshold={0.3}
        ListEmptyComponent={
          loading ? <Loading label="加载商品..." /> : error ? (
            <EmptyState
              icon={Package}
              title="加载失败"
              message={error}
              error
              onRetry={handleRefresh}
            />
          ) : (
            <EmptyState
              icon={Package}
              title="暂无商品"
              message={selectedAccountId ? '该账号暂无已发布商品' : '暂无已发布商品'}
            />
          )
        }
        ListFooterComponent={
          loadingMore ? (
            <View style={styles.footer}>
              <ActivityIndicator size="small" color={c.primary} />
            </View>
          ) : items.length > 0 && page >= totalPages && totalPages > 0 ? (
            <Text style={[styles.footerText, { color: c.textMuted }]}>没有更多了</Text>
          ) : null
        }
      />

      {/* 商品 → 关联卡券弹窗 */}
      <ItemCardRelationModal
        itemId={relationItem?.item_id ?? ''}
        itemName={relationItem?.title ?? ''}
        visible={!!relationItem}
        onClose={() => setRelationItem(null)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  toolbar: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.sm },
  accountBar: {
    borderBottomWidth: 1,
    paddingBottom: spacing.sm,
  },
  chipRowScroll: { gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: 2 },
  chip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.full,
    borderWidth: 1,
    maxWidth: 160,
  },
  chipText: { ...typography.small },
  countText: {
    ...typography.small,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.xs,
  },
  historyRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: spacing.lg },
  list: { padding: spacing.lg, gap: spacing.md },
  card: { padding: spacing.md },
  cardRow: { flexDirection: 'row', gap: spacing.md },
  thumb: {
    width: 56,
    height: 56,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
  },
  body: { flex: 1, gap: spacing.xs, justifyContent: 'space-between' },
  title: { ...typography.caption, fontWeight: '600', lineHeight: 20 },
  metaRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap' },
  price: { ...typography.caption, fontWeight: '700' },
  qty: { ...typography.small },
  actionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginTop: spacing.sm,
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    alignSelf: 'flex-end',
    paddingHorizontal: spacing.xs,
  },
  actionText: { ...typography.small, fontWeight: '600' },
  footer: { paddingVertical: spacing.lg, alignItems: 'center' },
  footerText: { ...typography.small, textAlign: 'center', paddingVertical: spacing.md },
});
