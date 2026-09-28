import { useState, useCallback, useEffect, useRef } from 'react';
import {
  View, Text, StyleSheet, ScrollView, RefreshControl, Pressable, Alert, useColorScheme,
} from 'react-native';
import { useFocusEffect } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Card, Button, Loading } from '@/components/ui';
import { colors, spacing, typography, radius } from '@/lib/theme';
import { useAuthStore } from '@/stores/auth';
import { useConfigStore } from '@/stores/config';
import { getAccountOptions, getAccountDetailsPaginated, type AccountOption } from '@/api/wrappers/accounts';
import {
  getPublishMaterials, publishBatch, getBatchPublishProgress, PublishBatchUnavailableError,
  type PublishMaterialOption, type BatchPublishProgress,
} from '@/api/wrappers/product-publish';

type BatchRecord = {
  kind: 'uncertain' | 'active' | 'finished';
  batchId?: string;
  accountIds: string[];
  materialIds: number[];
  startedAt?: string;
  progress?: BatchPublishProgress;
};

const POLL_INTERVAL_MS = 3000;
const MATERIAL_PAGE_SIZE = 100;

export default function ProductPublishScreen() {
  const scheme = useColorScheme();
  const c = colors[scheme === 'dark' ? 'dark' : 'light'];
  const userId = useAuthStore((state) => state.user?.user_id);
  const isAdmin = useAuthStore((state) => state.user?.is_admin);
  const serverUrl = useConfigStore((state) => state.serverUrl);
  const storageKey = serverUrl && userId != null
    ? 'publish_batch:' + encodeURIComponent(serverUrl) + ':' + userId
    : null;

  const [accounts, setAccounts] = useState<AccountOption[]>([]);
  const [materials, setMaterials] = useState<PublishMaterialOption[]>([]);
  const [materialPage, setMaterialPage] = useState(1);
  const [materialTotal, setMaterialTotal] = useState(0);
  const [selectedAccounts, setSelectedAccounts] = useState<Set<string>>(new Set());
  const [selectedMaterials, setSelectedMaterials] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(true);
  const [restored, setRestored] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [moreLoading, setMoreLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [checking, setChecking] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [statusError, setStatusError] = useState('');
  const [record, setRecord] = useState<BatchRecord | null>(null);
  const [progress, setProgress] = useState<BatchPublishProgress | null>(null);
  const submittingRef = useRef(false);
  const checkingRef = useRef(false);

  const persistRecord = useCallback(async (next: BatchRecord) => {
    if (!storageKey) throw new Error('登录状态尚未就绪');
    await AsyncStorage.setItem(storageKey, JSON.stringify(next));
    setRecord(next);
  }, [storageKey]);

  const loadOptions = useCallback(async () => {
    setRefreshing(true);
    setLoadError('');
    try {
      const getOwnAccountPks = async (): Promise<Set<number> | null> => {
        if (!isAdmin) return null;
        const own = new Set<number>();
        let page = 1;
        while (true) {
          const response = await getAccountDetailsPaginated(page, 100);
          response.data.forEach((account) => {
            if (account.owner_id === userId) own.add(account.pk);
          });
          if (page * 100 >= response.total) break;
          page += 1;
        }
        return own;
      };
      const [allAccounts, materialList, ownAccountPks] = await Promise.all([
        getAccountOptions(),
        getPublishMaterials(1, MATERIAL_PAGE_SIZE),
        getOwnAccountPks(),
      ]);
      const accountList = ownAccountPks
        ? allAccounts.filter((account) => ownAccountPks.has(account.pk))
        : allAccounts;
      const ownMaterials = materialList.list.filter((item) => item.user_id === userId);
      setAccounts(accountList);
      setMaterials(ownMaterials);
      setMaterialPage(1);
      setMaterialTotal(materialList.total);
      setSelectedAccounts((current) => new Set(
        Array.from(current).filter((id) => accountList.some((account) => account.id === id)),
      ));
      setSelectedMaterials((current) => new Set(
        Array.from(current).filter((id) => ownMaterials.some((item) => item.id === id)),
      ));
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : '加载账号或素材失败');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [isAdmin, userId]);

  useEffect(() => {
    if (!storageKey) return;
    let mounted = true;
    setRestored(false);
    setRecord(null);
    setProgress(null);
    setAccounts([]);
    setMaterials([]);
    setSelectedAccounts(new Set());
    setSelectedMaterials(new Set());
    setLoading(true);
    void (async () => {
      try {
        const raw = await AsyncStorage.getItem(storageKey);
        if (!mounted || !raw) return;
        const saved = JSON.parse(raw) as BatchRecord;
        if (!['uncertain', 'active', 'finished'].includes(saved.kind)) return;
        if (saved.kind === 'active' && !saved.batchId) return;
        setRecord(saved);
        setProgress(saved.progress ?? null);
      } catch {
        if (mounted) setStatusError('无法读取本地批次记录，请检查应用存储后再发布');
      } finally {
        if (mounted) setRestored(true);
      }
    })();
    void loadOptions();
    return () => { mounted = false; };
  }, [storageKey, loadOptions]);

  const loadMore = async () => {
    if (moreLoading || materialPage * MATERIAL_PAGE_SIZE >= materialTotal) return;
    setMoreLoading(true);
    try {
      const nextPage = materialPage + 1;
      const page = await getPublishMaterials(nextPage, MATERIAL_PAGE_SIZE);
      setMaterials((current) => {
        const ids = new Set(current.map((item) => item.id));
        return [...current, ...page.list.filter((item) => item.user_id === userId && !ids.has(item.id))];
      });
      setMaterialPage(nextPage);
      setMaterialTotal(page.total);
    } catch (error) {
      Alert.alert('加载素材失败', error instanceof Error ? error.message : '请稍后重试');
    } finally {
      setMoreLoading(false);
    }
  };

  useFocusEffect(useCallback(() => {
    if (!storageKey || !restored || record?.kind !== 'active' || !record.batchId) return;
    let focused = true;
    const batchId = record.batchId;
    const check = async () => {
      if (checkingRef.current) return;
      checkingRef.current = true;
      try {
        const latest = await getBatchPublishProgress(batchId);
        if (!focused) return;
        setProgress(latest);
        setStatusError('');
        if (!latest.snapshot_available) {
          const unresolved: BatchRecord = { ...record, kind: 'uncertain', progress: latest };
          try { await persistRecord(unresolved); } catch { setRecord(unresolved); }
          setStatusError('仅恢复到部分发布日志，无法确认任务是否完成。请核实后再发起新批次。');
        } else if (latest.finished) {
          const finished: BatchRecord = { ...record, kind: 'finished', progress: latest };
          try { await persistRecord(finished); } catch { setRecord(finished); }
        }
      } catch (error) {
        if (focused && error instanceof PublishBatchUnavailableError) {
          const unresolved: BatchRecord = { ...record, kind: 'uncertain' };
          try { await persistRecord(unresolved); } catch { setRecord(unresolved); }
          setStatusError(error.message + '。请核实服务端日志与平台商品。');
        } else if (focused) {
          setStatusError(error instanceof Error ? error.message : '查询任务状态失败');
        }
      } finally {
        checkingRef.current = false;
      }
    };
    void check();
    const timer = setInterval(() => { void check(); }, POLL_INTERVAL_MS);
    return () => { focused = false; clearInterval(timer); };
  }, [storageKey, restored, record, persistRecord]));

  const toggleAccount = (id: string) => {
    setSelectedAccounts((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const toggleMaterial = (id: number) => {
    setSelectedMaterials((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const submit = async () => {
    if (submittingRef.current || !storageKey || !restored || record?.kind === 'active' || record?.kind === 'uncertain') return;
    const accountIds = Array.from(selectedAccounts);
    const materialIds = Array.from(selectedMaterials);
    if (!accountIds.length || !materialIds.length) return;
    submittingRef.current = true;
    setSubmitting(true);
    setStatusError('');
    const uncertain: BatchRecord = {
      kind: 'uncertain', accountIds, materialIds, startedAt: new Date().toLocaleString(),
    };
    try {
      // Write before POST: a lost response or app crash must never offer blind resubmission.
      await persistRecord(uncertain);
    } catch (error) {
      Alert.alert('无法提交', error instanceof Error ? error.message : '无法保存本地任务记录');
      submittingRef.current = false;
      setSubmitting(false);
      return;
    }
    try {
      const started = await publishBatch(accountIds, materialIds);
      const active: BatchRecord = { ...uncertain, kind: 'active', batchId: started.batch_id };
      setProgress({
        batch_id: started.batch_id,
        total: started.total,
        success: 0, failed: 0, unknown: 0, skipped: 0,
        publishing: 0, pending: started.total,
        finished: false, snapshot_available: true, account_statuses: [],
      });
      try {
        await persistRecord(active);
      } catch {
        setRecord(active);
        setStatusError('任务已提交，但本地任务 ID 保存失败。离开页面前请记下任务 ID。');
      }
    } catch {
      setStatusError('提交结果无法确认。请先查看服务端发布日志和闲鱼账号，勿直接重复提交。');
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  const confirmSubmit = () => {
    const total = selectedAccounts.size * selectedMaterials.size;
    if (!total || submittingRef.current) return;
    Alert.alert(
      '确认批量发布',
      '将向 ' + selectedAccounts.size + ' 个账号发布 ' + selectedMaterials.size
        + ' 条素材，共 ' + total + ' 次。素材中的宝贝所在地会由随机地址库分配。',
      [
        { text: '取消', style: 'cancel' },
        { text: '确认提交', onPress: () => { void submit(); } },
      ],
    );
  };

  const retryStatus = async () => {
    if (!record?.batchId || checking) return;
    setChecking(true);
    try {
      const latest = await getBatchPublishProgress(record.batchId);
      setProgress(latest);
      if (latest.snapshot_available) {
        const next: BatchRecord = {
          ...record, kind: latest.finished ? 'finished' : 'active', progress: latest,
        };
        await persistRecord(next);
        setStatusError('');
      } else {
        setStatusError('仍只能看到部分日志，无法确认任务完成。');
      }
    } catch (error) {
      setStatusError(error instanceof Error ? error.message : '查询任务状态失败');
    } finally {
      setChecking(false);
    }
  };

  const clearRecord = () => {
    if (!storageKey || record?.kind === 'active') return;
    Alert.alert(
      '已核实发布结果？',
      '请先检查发布日志与闲鱼账号。清除本地记录不会取消服务端任务，且可能导致重复发布。',
      [
        { text: '取消', style: 'cancel' },
        { text: '已核实，清除', onPress: () => {
          void AsyncStorage.removeItem(storageKey).then(() => {
            setRecord(null);
            setProgress(null);
            setStatusError('');
          }).catch((error) => {
            Alert.alert('清除失败', error instanceof Error ? error.message : '请稍后重试');
          });
        } },
      ],
    );
  };

  const blocked = !restored || !storageKey || !!statusError && !record
    || submitting || record?.kind === 'active' || record?.kind === 'uncertain';
  const completed = progress
    ? progress.success + progress.failed + progress.unknown + progress.skipped
    : 0;

  if (loading && !accounts.length && !materials.length) {
    return (
      <SafeAreaView style={[styles.container, { backgroundColor: c.background }]} edges={['left', 'right', 'bottom']}>
        <Loading label="加载账号和素材..." />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: c.background }]} edges={['left', 'right', 'bottom']}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={loadOptions} />}
      >
        <View style={[styles.banner, { backgroundColor: c.primaryLight }]}>
          <Text style={[styles.caption, { color: c.primary }]}>
            批量发布按账号逐条执行。素材中的宝贝所在地会由随机地址库分配。
          </Text>
        </View>

        {loadError ? <Text style={[styles.caption, { color: c.error }]}>{loadError}</Text> : null}

        <Card style={styles.section}>
          <Text style={[styles.heading, { color: c.text }]}>选择账号 ({selectedAccounts.size})</Text>
          {accounts.length === 0 ? (
            <Text style={[styles.caption, { color: c.textMuted }]}>暂无账号，请先添加闲鱼账号。</Text>
          ) : accounts.map((account) => {
            const selected = selectedAccounts.has(account.id);
            return (
              <Pressable
                key={account.id}
                accessibilityRole="checkbox"
                accessibilityState={{ checked: selected }}
                onPress={() => toggleAccount(account.id)}
                style={[styles.option, { borderColor: selected ? c.primary : c.border, backgroundColor: selected ? c.primaryLight : c.surface }]}
              >
                <Text style={[styles.check, { color: c.primary }]}>{selected ? '☑' : '□'}</Text>
                <View style={styles.optionBody}>
                  <Text style={[styles.optionTitle, { color: c.text }]} numberOfLines={1}>{account.remark || account.id}</Text>
                  {account.remark ? <Text style={[styles.small, { color: c.textMuted }]} numberOfLines={1}>{account.id}</Text> : null}
                </View>
                <Text style={[styles.small, { color: account.enabled ? c.success : c.textMuted }]}>
                  {account.enabled ? '已启用' : '未启用'}
                </Text>
              </Pressable>
            );
          })}
        </Card>

        <Card style={styles.section}>
          <Text style={[styles.heading, { color: c.text }]}>选择素材 ({selectedMaterials.size})</Text>
          {materials.length === 0 ? (
            <Text style={[styles.caption, { color: c.textMuted }]}>
              {materialTotal > 0 && materialPage * MATERIAL_PAGE_SIZE < materialTotal
                ? '当前页暂无自己的素材，可继续加载后续页。'
                : '暂无可发布的自有素材，请先在 Web 素材库创建商品。'}
            </Text>
          ) : materials.map((material) => {
            const selected = selectedMaterials.has(material.id);
            return (
              <Pressable
                key={material.id}
                accessibilityRole="checkbox"
                accessibilityState={{ checked: selected }}
                onPress={() => toggleMaterial(material.id)}
                style={[styles.option, { borderColor: selected ? c.primary : c.border, backgroundColor: selected ? c.primaryLight : c.surface }]}
              >
                <Text style={[styles.check, { color: c.primary }]}>{selected ? '☑' : '□'}</Text>
                <View style={styles.optionBody}>
                  <Text style={[styles.optionTitle, { color: c.text }]} numberOfLines={2}>{material.title}</Text>
                  <Text style={[styles.small, { color: c.textSecondary }]}>¥{material.price}</Text>
                </View>
              </Pressable>
            );
          })}
          {materialPage * MATERIAL_PAGE_SIZE < materialTotal ? (
            <Button label={'加载更多 (第 ' + materialPage + '/' + Math.ceil(materialTotal / MATERIAL_PAGE_SIZE) + ' 页)'} variant="secondary" onPress={() => { void loadMore(); }} loading={moreLoading} />
          ) : null}
        </Card>

        <Card style={styles.section}>
          <Text style={[styles.heading, { color: c.text }]}>发布计划</Text>
          <Text style={[styles.caption, { color: c.textSecondary }]}>
            {selectedAccounts.size} 个账号 × {selectedMaterials.size} 条素材 = {selectedAccounts.size * selectedMaterials.size} 次发布
          </Text>
          <Button
            label={record?.kind === 'active' ? '任务进行中' : record?.kind === 'uncertain' ? '请先核实上一批次' : '确认并提交'}
            onPress={confirmSubmit}
            loading={submitting}
            disabled={blocked || selectedAccounts.size === 0 || selectedMaterials.size === 0}
          />
        </Card>

        {record ? (
          <Card style={styles.section}>
            <Text style={[styles.heading, { color: c.text }]}>当前批次</Text>
            {record.batchId ? <Text selectable style={[styles.small, { color: c.textMuted }]}>任务 ID: {record.batchId}</Text> : null}
            {record.kind === 'uncertain' ? (
              <>
                {record.startedAt ? <Text style={[styles.small, { color: c.textSecondary }]}>提交时间：{record.startedAt}</Text> : null}
                <Text selectable style={[styles.small, { color: c.textSecondary }]}>需核实账号：{record.accountIds.join('、')}</Text>
                <Text selectable style={[styles.small, { color: c.textSecondary }]}>需核实素材 ID：{record.materialIds.join('、')}</Text>
              </>
            ) : null}
            <Text style={[styles.caption, { color: record.kind === 'uncertain' ? c.warning : c.textSecondary }]}>
              {record.kind === 'active' ? '执行中，正在查询进度'
                : record.kind === 'finished' ? '任务已结束'
                  : '结果未确认，请核实服务端日志与平台商品'}
            </Text>
            {progress ? (
              <>
                <Text style={[styles.caption, { color: c.text }]}>已处理 {completed}/{progress.total} · 发布中 {progress.publishing} · 待处理 {progress.pending}</Text>
                <Text style={[styles.caption, { color: c.success }]}>成功 {progress.success}</Text>
                <Text style={[styles.caption, { color: c.error }]}>失败 {progress.failed}</Text>
                <Text style={[styles.caption, { color: c.warning }]}>跳过 {progress.skipped} · 结果未知 {progress.unknown}</Text>
                {progress.unknown > 0 ? (
                  <Text style={[styles.caption, { color: c.warning }]}>结果未知的商品须先到闲鱼核实，勿直接重新发布。</Text>
                ) : null}
                {!progress.snapshot_available ? (
                  <Text style={[styles.caption, { color: c.warning }]}>仅恢复到部分发布日志，不能据此确认任务结束。</Text>
                ) : null}
                {progress.account_statuses.map((item) => (
                  <View key={item.account_id} style={[styles.accountProgress, { borderTopColor: c.border }]}>
                    <Text style={[styles.optionTitle, { color: c.text }]}>{item.account_id}</Text>
                    <Text style={[styles.small, { color: c.textSecondary }]}>
                      成功 {item.success} · 失败 {item.failed} · 跳过 {item.skipped} · 未知 {item.unknown} · 待处理 {item.pending}
                    </Text>
                    <Text style={[styles.small, { color: item.sync_status === 'failed' || item.sync_status === 'unknown' ? c.warning : c.textMuted }]}>
                      自动获取商品：{item.sync_message}
                    </Text>
                  </View>
                ))}
              </>
            ) : null}
            {statusError ? <Text style={[styles.caption, { color: c.warning }]}>{statusError}</Text> : null}
            {record.kind === 'uncertain' && record.batchId ? (
              <Button label="重新查询任务状态" variant="secondary" onPress={() => { void retryStatus(); }} loading={checking} />
            ) : null}
            {record.kind !== 'active' ? (
              <Button label="已核实，清除批次记录" variant="secondary" onPress={clearRecord} />
            ) : null}
          </Card>
        ) : statusError ? <Text style={[styles.caption, { color: c.warning }]}>{statusError}</Text> : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxxl },
  banner: { borderRadius: radius.md, padding: spacing.md },
  section: { gap: spacing.sm },
  heading: { ...typography.heading },
  caption: { ...typography.caption },
  small: { ...typography.small },
  option: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    padding: spacing.md, borderWidth: 1, borderRadius: radius.md,
  },
  check: { fontSize: 22, width: 25 },
  optionBody: { flex: 1, gap: 2 },
  optionTitle: { ...typography.caption, fontWeight: '600' },
  accountProgress: { borderTopWidth: StyleSheet.hairlineWidth, paddingTop: spacing.sm, gap: 2 },
});
