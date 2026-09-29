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
  getPublishMaterials, publishBatch, getBatchPublishProgress, getBatchPublishTargets, retryPublishBatch,
  PublishBatchUnavailableError,
  type PublishMaterialOption, type BatchPublishProgress, type PublishBatchTarget, type PublishWindowHours,
} from '@/api/wrappers/product-publish';

type BatchRecord = {
  kind: 'uncertain' | 'active' | 'finished';
  batchId?: string;
  accountIds: string[];
  materialIds: number[];
  startedAt?: string;
  progress?: BatchPublishProgress;
  windowHours?: PublishWindowHours;
  retryTargetIds?: number[];
};

const POLL_INTERVAL_MS = 3000;
const MATERIAL_PAGE_SIZE = 100;

export default function ProductPublishScreen() {
  const userId = useAuthStore((state) => state.user?.user_id);
  const serverUrl = useConfigStore((state) => state.serverUrl);
  if (userId == null || !serverUrl) return null;
  return <ProductPublishContent key={JSON.stringify([serverUrl, userId])} userId={userId} serverUrl={serverUrl} />;
}

function ProductPublishContent({ userId, serverUrl }: { userId: number; serverUrl: string }) {
  const scheme = useColorScheme();
  const c = colors[scheme === 'dark' ? 'dark' : 'light'];
  const isAdmin = useAuthStore((state) => state.user?.is_admin);
  const storageKey = 'publish_batch:' + encodeURIComponent(serverUrl) + ':' + userId;

  const [accounts, setAccounts] = useState<AccountOption[]>([]);
  const [materials, setMaterials] = useState<PublishMaterialOption[]>([]);
  const [materialPage, setMaterialPage] = useState(1);
  const [materialTotal, setMaterialTotal] = useState(0);
  const [selectedAccounts, setSelectedAccounts] = useState<Set<string>>(new Set());
  const [selectedMaterials, setSelectedMaterials] = useState<Set<number>>(new Set());
  const [windowHours, setWindowHours] = useState<PublishWindowHours | null>(null);
  const [loading, setLoading] = useState(true);
  const [restored, setRestored] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [moreLoading, setMoreLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [checking, setChecking] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [statusError, setStatusError] = useState('');
  const [record, setRecord] = useState<BatchRecord | null>(null);
  const [progress, setProgress] = useState<BatchPublishProgress | null>(null);
  const [targets, setTargets] = useState<PublishBatchTarget[]>([]);
  const [targetPage, setTargetPage] = useState(1);
  const [targetTotal, setTargetTotal] = useState(0);
  const [selectedRetryTargetIds, setSelectedRetryTargetIds] = useState<Set<number>>(new Set());
  const [retryWindowHours, setRetryWindowHours] = useState<PublishWindowHours | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [clearing, setClearing] = useState(false);
  const targetPageRef = useRef(1);
  const targetStatusRef = useRef(new Map<number, string>());
  const detailLoadingRef = useRef(false);
  const submittingRef = useRef(false);
  const checkingRef = useRef(false);
  const retryingRef = useRef(false);
  const statusGenerationRef = useRef(0);
  const detailGenerationRef = useRef(0);
  const clearGenerationRef = useRef(0);
  const clearingRef = useRef(false);
  const storageOperationRef = useRef(Promise.resolve());

  const persistRecord = useCallback(async (next: BatchRecord) => {
    if (!storageKey) throw new Error('登录状态尚未就绪');
    const generation = clearGenerationRef.current;
    if (clearingRef.current) throw new Error('批次记录正在清除');
    const operation = storageOperationRef.current.then(async () => {
      if (generation !== clearGenerationRef.current || clearingRef.current) {
        throw new Error('批次记录已清除');
      }
      await AsyncStorage.setItem(storageKey, JSON.stringify(next));
      if (generation !== clearGenerationRef.current || clearingRef.current) {
        throw new Error('批次记录已清除');
      }
      setRecord(next);
    });
    storageOperationRef.current = operation.then(() => undefined, () => undefined);
    await operation;
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
    setTargets([]);
    setTargetPage(1);
    targetPageRef.current = 1;
    targetStatusRef.current.clear();
    setTargetTotal(0);
    setSelectedRetryTargetIds(new Set());
    setRetryWindowHours(null);
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

  const requestDetails = useCallback(async (batchId: string, page: number) => {
    if (clearingRef.current) return;
    const clearGeneration = clearGenerationRef.current;
    const generation = ++detailGenerationRef.current;
    detailLoadingRef.current = true;
    setDetailLoading(true);
    try {
      const detail = await getBatchPublishTargets(batchId, page, 20);
      if (generation !== detailGenerationRef.current || clearGeneration !== clearGenerationRef.current || clearingRef.current) return;
      setTargets(detail.list);
      detail.list.forEach((target) => targetStatusRef.current.set(target.id, target.status));
      setTargetPage(detail.page);
      targetPageRef.current = detail.page;
      setTargetTotal(detail.total);
    } catch (error) {
      if (generation === detailGenerationRef.current) {
        setStatusError(error instanceof Error ? error.message : '查询任务详情失败');
      }
    } finally {
      if (generation === detailGenerationRef.current) {
        detailLoadingRef.current = false;
        setDetailLoading(false);
      }
    }
  }, []);

  useFocusEffect(useCallback(() => {
    if (!storageKey || !restored || record?.kind === 'uncertain' || !record?.batchId) return;
    const batchId = record.batchId;
    if (record.kind !== 'active') {
      void requestDetails(batchId, targetPageRef.current);
      return () => {
        ++detailGenerationRef.current;
        detailLoadingRef.current = false;
        setDetailLoading(false);
      };
    }
    const check = async () => {
      if (checkingRef.current) return;
      checkingRef.current = true;
      const generation = ++statusGenerationRef.current;
      setChecking(true);
      try {
        const latest = await getBatchPublishProgress(batchId);
        if (generation !== statusGenerationRef.current) return;
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
        if (generation !== statusGenerationRef.current) return;
        if (error instanceof PublishBatchUnavailableError) {
          const unresolved: BatchRecord = { ...record, kind: 'uncertain' };
          try { await persistRecord(unresolved); } catch { setRecord(unresolved); }
          setStatusError(error.message + '。请核实服务端日志与平台商品。');
        } else {
          setStatusError(error instanceof Error ? error.message : '查询任务状态失败');
        }
      } finally {
        if (generation === statusGenerationRef.current) {
          checkingRef.current = false;
          setChecking(false);
        }
      }
    };
    void check();
    void requestDetails(batchId, targetPageRef.current);
    const timer = setInterval(() => {
      void check();
      if (!detailLoadingRef.current) void requestDetails(batchId, targetPageRef.current);
    }, POLL_INTERVAL_MS);
    return () => {
      ++statusGenerationRef.current;
      ++detailGenerationRef.current;
      checkingRef.current = false;
      setChecking(false);
      detailLoadingRef.current = false;
      setDetailLoading(false);
      clearInterval(timer);
    };
  }, [storageKey, restored, record, persistRecord, requestDetails]));

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

  const toggleRetryTarget = (target: PublishBatchTarget) => {
    if (target.status !== 'failed') return;
    setSelectedRetryTargetIds((current) => {
      const next = new Set(current);
      if (next.has(target.id)) next.delete(target.id); else next.add(target.id);
      return next;
    });
  };

  const retryFailed = async () => {
    if (!record?.batchId || record.kind !== 'finished' || clearingRef.current || retryingRef.current || retryWindowHours === null) return;
    const targetIds = Array.from(selectedRetryTargetIds).filter((id) => targetStatusRef.current.get(id) === 'failed');
    if (!targetIds.length) {
      setStatusError('请重新加载详情后选择明确失败项。');
      return;
    }
    retryingRef.current = true;
    setRetrying(true);
    setStatusError('');
    const uncertain: BatchRecord = {
      ...record, kind: 'uncertain', retryTargetIds: targetIds, windowHours: retryWindowHours,
    };
    try {
      // Write before POST: a lost response must leave this batch blocked from blind retry.
      await persistRecord(uncertain);
    } catch (error) {
      setStatusError(error instanceof Error ? error.message : '无法保存重试记录');
      retryingRef.current = false;
      setRetrying(false);
      return;
    }
    try {
      const result = await retryPublishBatch(record.batchId, targetIds, retryWindowHours);
      if (result.retried !== targetIds.length) {
        throw new Error('服务端仅受理了部分重试项，结果无法安全确认，请核实日志，勿重复提交');
      }
      const active: BatchRecord = { ...uncertain, kind: 'active', retryTargetIds: undefined };
      await persistRecord(active);
      setProgress((current) => current ? {
        ...current,
        status: 'running',
        finished: false,
        window_hours: retryWindowHours,
      } : current);
      setSelectedRetryTargetIds(new Set());
      setRetryWindowHours(null);
    } catch (error) {
      setStatusError(error instanceof Error ? error.message : '重试结果无法确认，请先核实服务端日志，勿重复提交');
    } finally {
      retryingRef.current = false;
      setRetrying(false);
    }
  };

  const confirmRetry = () => {
    if (!record?.batchId || record.kind !== 'finished' || clearingRef.current || retryingRef.current || retryWindowHours === null || selectedRetryTargetIds.size === 0) return;
    Alert.alert(
      '确认重试失败项',
      '将重试 ' + selectedRetryTargetIds.size + ' 个明确失败项，窗口：' + retryWindowHours + ' 小时。成功、结果未知和跳过项不会重试。',
      [
        { text: '取消', style: 'cancel' },
        { text: '确认重试', onPress: () => { void retryFailed(); } },
      ],
    );
  };

  const submit = async () => {
    if (submittingRef.current || clearingRef.current || !storageKey || !restored || record?.kind === 'active' || record?.kind === 'uncertain') return;
    const accountIds = Array.from(selectedAccounts);
    const materialIds = Array.from(selectedMaterials);
    if (!accountIds.length || !materialIds.length || windowHours === null) return;
    submittingRef.current = true;
    setSubmitting(true);
    setStatusError('');
    ++statusGenerationRef.current;
    ++detailGenerationRef.current;
    targetPageRef.current = 1;
    targetStatusRef.current.clear();
    setTargets([]);
    setTargetPage(1);
    setTargetTotal(0);
    setSelectedRetryTargetIds(new Set());
    setRetryWindowHours(null);
    const uncertain: BatchRecord = {
      kind: 'uncertain', accountIds, materialIds, windowHours, startedAt: new Date().toLocaleString(),
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
      const started = await publishBatch(accountIds, materialIds, windowHours);
      const active: BatchRecord = { ...uncertain, kind: 'active', batchId: started.batch_id };
      setProgress({
        batch_id: started.batch_id,
        window_hours: windowHours,
        window_started_at: null,
        deadline_at: null,
        timed_out: 0,
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
    if (!total || submittingRef.current || windowHours === null) return;
    Alert.alert(
      '确认批量发布',
      '将向 ' + selectedAccounts.size + ' 个账号发布 ' + selectedMaterials.size
        + ' 条素材，共 ' + total + ' 次。窗口：' + windowHours + ' 小时。素材中的宝贝所在地会由随机地址库分配。',
      [
        { text: '取消', style: 'cancel' },
        { text: '确认提交', onPress: () => { void submit(); } },
      ],
    );
  };

  const retryStatus = async () => {
    if (!record?.batchId || checkingRef.current || clearingRef.current) return;
    checkingRef.current = true;
    setChecking(true);
    const clearGeneration = clearGenerationRef.current;
    const generation = ++statusGenerationRef.current;
    try {
      const latest = await getBatchPublishProgress(record.batchId);
      if (generation !== statusGenerationRef.current || clearGeneration !== clearGenerationRef.current || clearingRef.current) return;
      setProgress(latest);
      if (latest.snapshot_available) {
        const next: BatchRecord = {
          ...record,
          kind: record.retryTargetIds?.length ? 'uncertain' : latest.finished ? 'finished' : 'active',
          progress: latest,
        };
        try {
          await persistRecord(next);
          setStatusError(record.retryTargetIds?.length
            ? '重试请求结果仍无法确认，请核实服务端日志，勿重复提交。'
            : '');
        } catch (error) {
          setStatusError(error instanceof Error ? error.message : '保存批次状态失败');
        }
      } else {
        setStatusError('仍只能看到部分日志，无法确认任务完成。');
      }
    } catch (error) {
      if (generation === statusGenerationRef.current) {
        setStatusError(error instanceof Error ? error.message : '查询任务状态失败');
      }
    } finally {
      if (generation === statusGenerationRef.current) {
        checkingRef.current = false;
        setChecking(false);
      }
    }
    void requestDetails(record.batchId, targetPageRef.current);
  };

  const loadTargetPage = async (page: number) => {
    if (!record?.batchId || detailLoading) return;
    void requestDetails(record.batchId, page);
  };

  const clearRecord = () => {
    if (!storageKey || record?.kind === 'active' || clearingRef.current) return;
    Alert.alert(
      '已核实发布结果？',
      '请先检查发布日志与闲鱼账号。清除本地记录不会取消服务端任务，且可能导致重复发布。',
      [
        { text: '取消', style: 'cancel' },
        { text: '已核实，清除', onPress: () => {
          const clearGeneration = ++clearGenerationRef.current;
          clearingRef.current = true;
          setClearing(true);
          ++statusGenerationRef.current;
          ++detailGenerationRef.current;
          checkingRef.current = false;
          detailLoadingRef.current = false;
          targetPageRef.current = 1;
          targetStatusRef.current.clear();
          setChecking(false);
          setDetailLoading(false);
          setTargets([]);
          setTargetPage(1);
          setTargetTotal(0);
          setSelectedRetryTargetIds(new Set());
          setRetryWindowHours(null);
          void storageOperationRef.current.then(async () => {
            if (clearGeneration !== clearGenerationRef.current) return;
            await AsyncStorage.removeItem(storageKey);
            setRecord(null);
            setProgress(null);
            setStatusError('');
          }).catch((error) => {
            Alert.alert('清除失败', error instanceof Error ? error.message : '请稍后重试');
          }).finally(() => {
            if (clearGeneration === clearGenerationRef.current) {
              clearingRef.current = false;
              setClearing(false);
            }
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
          <Text style={[styles.caption, { color: c.textSecondary }]}>必须选择窗口，提交不会预选默认值。</Text>
          <View style={styles.windowRow}>
            {([1, 3, 5, 12, 24] as PublishWindowHours[]).map((hours) => (
              <Pressable key={hours} onPress={() => setWindowHours(hours)} style={[styles.windowOption, { borderColor: windowHours === hours ? c.primary : c.border, backgroundColor: windowHours === hours ? c.primaryLight : c.surface }]}>
                <Text style={[styles.small, { color: windowHours === hours ? c.primary : c.text }]}>{hours} 小时</Text>
              </Pressable>
            ))}
          </View>
          <Text style={[styles.caption, { color: c.textSecondary }]}>
            {selectedAccounts.size} 个账号 × {selectedMaterials.size} 条素材 = {selectedAccounts.size * selectedMaterials.size} 次发布
          </Text>
          <Button
            label={record?.kind === 'active' ? '任务进行中' : record?.kind === 'uncertain' ? '请先核实上一批次' : '确认并提交'}
            onPress={confirmSubmit}
            loading={submitting}
            disabled={blocked || clearing || windowHours === null || selectedAccounts.size === 0 || selectedMaterials.size === 0}
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
                <Text style={[styles.caption, { color: c.textSecondary }]}>窗口：{progress.window_hours ? progress.window_hours + ' 小时' : '—'} · 开始：{progress.window_started_at || '—'} · 截止：{progress.deadline_at || '—'} · 超时：{progress.timed_out}</Text>
                {progress.timed_out > 0 ? <Text style={[styles.caption, { color: c.warning }]}>存在超时项目；明确平台成功仍保留超时原因，不伪装为全部按时成功。</Text> : null}
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
                {targets.map((target) => {
                  const retryable = record.kind === 'finished' && target.status === 'failed';
                  const selectedForRetry = selectedRetryTargetIds.has(target.id);
                  return (
                  <View key={target.id} style={[styles.accountProgress, { borderTopColor: c.border }] }>
                    {retryable ? (
                      <Pressable
                        accessibilityRole="checkbox"
                        accessibilityState={{ checked: selectedForRetry }}
                        onPress={() => toggleRetryTarget(target)}
                        style={[styles.option, { borderColor: selectedForRetry ? c.primary : c.border, backgroundColor: selectedForRetry ? c.primaryLight : c.surface }]}
                      >
                        <Text style={[styles.check, { color: c.primary }]}>{selectedForRetry ? '☑' : '□'}</Text>
                        <Text style={[styles.optionTitle, { color: c.text }]}>选择重试：{target.account_id} · {target.title}</Text>
                      </Pressable>
                    ) : null}
                    <Text style={[styles.optionTitle, { color: c.text }]}>{target.account_id} · {target.title}</Text>
                    <Text style={[styles.small, { color: c.textSecondary }]}>计划 {target.scheduled_at || '—'} · 截止 {target.deadline_at || '—'}</Text>
                    <Text style={[styles.small, { color: c.textSecondary }]}>请求发起 {target.request_started_at || '—'} · 最小间隔 {target.minimum_gap_seconds} 秒</Text>
                    {target.schedule_error ? <Text style={[styles.small, { color: c.warning }]}>超时/排程原因：{target.schedule_error}</Text> : null}
                    {target.error_message ? <Text style={[styles.small, { color: c.warning }]}>{target.error_message}</Text> : null}
                    {target.attempts.map((attempt) => <Text key={attempt.id} style={[styles.small, { color: c.textMuted }]}>尝试 #{attempt.attempt_no} · {attempt.status} · 计划 {attempt.scheduled_at || '—'} · 截止 {attempt.deadline_at || '—'}{attempt.schedule_error ? ' · ' + attempt.schedule_error : ''}</Text>)}
                  </View>
                  );
                })}
                {targetTotal > 20 ? <View style={styles.paginationRow}>
                  <Button label="上一页" variant="secondary" onPress={() => { void loadTargetPage(targetPage - 1); }} disabled={targetPage <= 1 || detailLoading} />
                  <Text style={[styles.small, { color: c.textMuted }]}>{detailLoading ? '加载中…' : '第 ' + targetPage + ' 页'}</Text>
                  <Button label="下一页" variant="secondary" onPress={() => { void loadTargetPage(targetPage + 1); }} disabled={targetPage * 20 >= targetTotal || detailLoading} />
                </View> : null}
                {progress.account_statuses.map((item) => (
                  <View key={item.account_id} style={[styles.accountProgress, { borderTopColor: c.border }] }>
                    <Text style={[styles.optionTitle, { color: c.text }]}>{item.account_id}</Text>
                    <Text style={[styles.small, { color: c.textSecondary }]}>成功 {item.success} · 失败 {item.failed} · 跳过 {item.skipped} · 未知 {item.unknown} · 待处理 {item.pending}</Text>
                    <Text style={[styles.small, { color: item.sync_status === 'failed' || item.sync_status === 'unknown' ? c.warning : c.textMuted }]}>自动获取商品：{item.sync_message}</Text>
                  </View>
                ))}
              </>
            ) : null}
            {statusError ? <Text style={[styles.caption, { color: c.warning }]}>{statusError}</Text> : null}
            {record.kind === 'uncertain' && record.batchId ? (
              <Button label="重新查询任务状态" variant="secondary" onPress={() => { void retryStatus(); }} loading={checking} />
            ) : null}
            {record.kind === 'finished' ? (
              <>
                <Text style={[styles.caption, { color: c.textSecondary }]}>只可选择明确失败项；成功、结果未知和跳过项不可重试。活动批次不可重试。</Text>
                <View style={styles.windowRow}>
                  {([1, 3, 5, 12, 24] as PublishWindowHours[]).map((hours) => (
                    <Pressable key={hours} onPress={() => setRetryWindowHours(hours)} style={[styles.windowOption, { borderColor: retryWindowHours === hours ? c.primary : c.border, backgroundColor: retryWindowHours === hours ? c.primaryLight : c.surface }]}>
                      <Text style={[styles.small, { color: retryWindowHours === hours ? c.primary : c.text }]}>{hours} 小时</Text>
                    </Pressable>
                  ))}
                </View>
                <Button
                  label="确认并重试失败项"
                  variant="secondary"
                  onPress={confirmRetry}
                  loading={retrying}
                  disabled={clearing || selectedRetryTargetIds.size === 0 || retryWindowHours === null}
                />
              </>
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
  windowRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  windowOption: { paddingVertical: spacing.sm, paddingHorizontal: spacing.md, borderWidth: 1, borderRadius: radius.md },
  paginationRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
});
