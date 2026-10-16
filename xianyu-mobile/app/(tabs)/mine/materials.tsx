import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert, Image, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View, useColorScheme,
} from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Image as ImageIcon, Package } from 'lucide-react-native';
import { Button, Card, EmptyState, Input, Loading } from '@/components/ui';
import { colors, radius, spacing, typography } from '@/lib/theme';
import { useAuthStore } from '@/stores/auth';
import { useConfigStore } from '@/stores/config';
import {
  createMaterial, deleteMaterial, getMaterial, getPublishMaterials, recommendMaterialCategory,
  updateMaterial, uploadProductImages,
  type MaterialCategoryCandidate, type MaterialInput, type ProductMaterial, type PublishMaterialOption,
} from '@/api/wrappers/product-publish';

const PAGE_SIZE = 50;
type ShippingMethod = NonNullable<MaterialInput['shipping_method']>;

type Draft = {
  title: string;
  description: string;
  price: string;
  originalPrice: string;
  images: string[];
  quantity: string;
  shippingMethod: ShippingMethod;
  postage: string;
  address: string;
  condition: string;
  categoryName: string;
  categoryCandidate: MaterialCategoryCandidate | null;
};

type Editor = {
  id: number | null;
  original: ProductMaterial | null;
  draft: Draft;
  categoryChanged: boolean;
};

const SHIPPING_OPTIONS: { value: ShippingMethod; label: string }[] = [
  { value: 'free', label: '包邮' },
  { value: 'distance', label: '按距离计费' },
  { value: 'fixed', label: '一口价运费' },
  { value: 'template', label: '运费模板' },
  { value: 'none', label: '无需邮寄' },
];

function draftFromMaterial(material: ProductMaterial | null): Draft {
  return {
    title: material?.title ?? '',
    description: material?.description ?? '',
    price: material ? String(material.price) : '',
    originalPrice: material?.original_price == null ? '' : String(material.original_price),
    images: material?.images ?? [],
    quantity: String(material?.quantity ?? 1),
    shippingMethod: material?.shipping_method ?? 'free',
    postage: String(material?.postage ?? 0),
    address: material?.address ?? '',
    condition: material?.condition ?? '全新',
    categoryName: material?.platform_category_name ?? material?.category ?? '',
    categoryCandidate: null,
  };
}

function previewUrl(image: string, serverUrl: string): string {
  if (/^(https?:|file:|data:)/i.test(image)) return image;
  return `${serverUrl.replace(/\/$/, '')}/${image.replace(/^\//, '')}`;
}

function categoryLabel(candidate: MaterialCategoryCandidate): string {
  return candidate.cat_name || candidate.channel_cat_name || candidate.path?.at(-1)?.name || '未命名分类';
}

// PUT supports partial updates. Do not normalize or overwrite fields the user did not edit.
function changedMaterialFields(editor: Editor, payload: MaterialInput): Partial<MaterialInput> {
  if (!editor.original) return payload;
  const before = draftFromMaterial(editor.original);
  const changes: Partial<MaterialInput> = { ...payload };
  const fields = {
    title: 'title', description: 'description', price: 'price', originalPrice: 'original_price',
    images: 'images', quantity: 'quantity', shippingMethod: 'shipping_method',
    postage: 'postage', address: 'address', condition: 'condition',
  } as const;
  for (const key of Object.keys(fields) as (keyof typeof fields)[]) {
    if (JSON.stringify(before[key]) === JSON.stringify(editor.draft[key])) delete changes[fields[key]];
  }
  if (before.shippingMethod !== editor.draft.shippingMethod) changes.postage = payload.postage;
  if ('address' in changes) changes.address_expected_text = null;
  return changes;
}

export default function MaterialsScreen() {
  const userId = useAuthStore((state) => state.user?.user_id);
  const serverUrl = useConfigStore((state) => state.serverUrl);
  if (userId == null || !serverUrl) return null;
  return <MaterialsContent key={JSON.stringify([serverUrl, userId])} userId={userId} serverUrl={serverUrl} />;
}

function MaterialsContent({ userId, serverUrl }: { userId: number; serverUrl: string }) {
  const scheme = useColorScheme();
  const c = colors[scheme === 'dark' ? 'dark' : 'light'];
  const router = useRouter();
  const { create, editId } = useLocalSearchParams<{ create?: string; editId?: string }>();
  const fromPublish = create === '1' || Boolean(editId);
  const [materials, setMaterials] = useState<PublishMaterialOption[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [editor, setEditor] = useState<Editor | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [recommending, setRecommending] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [candidates, setCandidates] = useState<MaterialCategoryCandidate[]>([]);
  const listRequest = useRef(0);
  const detailRequest = useRef(0);
  const editorVersion = useRef(0);
  const categoryVersion = useRef(0);
  const uploadPending = useRef(false);
  const mutationPending = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      ++listRequest.current;
      ++detailRequest.current;
      ++editorVersion.current;
      ++categoryVersion.current;
    };
  }, []);

  const loadPage = useCallback(async (nextPage: number, append = false) => {
    const request = ++listRequest.current;
    setLoadingMore(false);
    if (append) setLoadingMore(true);
    else setRefreshing(true);
    setLoadError('');
    try {
      const result = await getPublishMaterials(nextPage, PAGE_SIZE);
      if (request !== listRequest.current) return;
      const own = result.list.filter((item) => item.user_id === userId);
      setMaterials((current) => append
        ? [...current, ...own.filter((item) => !current.some((existing) => existing.id === item.id))]
        : own);
      setPage(nextPage);
      setTotal(result.total);
    } catch (error) {
      if (request === listRequest.current) setLoadError(error instanceof Error ? error.message : '加载素材失败');
    } finally {
      if (request === listRequest.current) {
        setLoading(false);
        setRefreshing(false);
        setLoadingMore(false);
      }
    }
  }, [userId]);

  useFocusEffect(useCallback(() => {
    void loadPage(1);
    return () => { ++listRequest.current; };
  }, [loadPage]));

  const openEditor = useCallback(async (id: number) => {
    if (mutationPending.current) return;
    if (!Number.isInteger(id) || id <= 0) {
      Alert.alert('加载详情失败', '素材 ID 无效');
      return;
    }
    ++editorVersion.current;
    const request = ++detailRequest.current;
    setRecommending(false);
    setDetailLoading(true);
    try {
      const material = await getMaterial(id);
      if (request !== detailRequest.current) return;
      if (material.user_id !== userId) throw new Error('只能编辑当前用户的素材');
      setCandidates([]);
      setEditor({ id, original: material, draft: draftFromMaterial(material), categoryChanged: false });
    } catch (error) {
      if (request === detailRequest.current) Alert.alert('加载详情失败', error instanceof Error ? error.message : '请稍后重试');
    } finally {
      if (request === detailRequest.current) setDetailLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    if (create === '1') {
      ++editorVersion.current;
      setEditor({ id: null, original: null, draft: draftFromMaterial(null), categoryChanged: false });
    } else if (editId) {
      void openEditor(Number(editId));
    }
  }, [create, editId, openEditor]);

  function openNew() {
    if (mutationPending.current) return;
    ++editorVersion.current;
    ++detailRequest.current;
    setRecommending(false);
    setCandidates([]);
    setEditor({ id: null, original: null, draft: draftFromMaterial(null), categoryChanged: false });
  }

  function closeEditor() {
    if (mutationPending.current) return;
    ++editorVersion.current;
    ++categoryVersion.current;
    setRecommending(false);
    ++detailRequest.current;
    if (fromPublish) router.back();
    else setEditor(null);
  }

  function updateDraft(patch: Partial<Draft>) {
    if (mutationPending.current) return;
    if ('title' in patch || 'description' in patch) {
      ++categoryVersion.current;
      setRecommending(false);
      setCandidates([]);
    }
    setEditor((current) => current ? { ...current, draft: { ...current.draft, ...patch } } : current);
  }

  async function pickImages() {
    if (!editor || uploadPending.current || mutationPending.current || editor.draft.images.length >= 9) return;
    const version = editorVersion.current;
    uploadPending.current = true;
    setUploading(true);
    try {
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images'], allowsMultipleSelection: true, allowsEditing: false,
        quality: 0.8, selectionLimit: 9 - editor.draft.images.length,
      });
      if (version !== editorVersion.current || result.canceled || !result.assets?.length) return;
      if (result.assets.some((asset) => (asset.fileSize || 0) > 5 * 1024 * 1024)) {
        throw new Error('每张图片不能超过 5MB，请选择较小的图片');
      }
      const uris = result.assets.map((asset) => asset.uri).filter(Boolean);
      if (!uris.length) return;
      const uploaded = await uploadProductImages(uris);
      if (version !== editorVersion.current) return;
      setEditor((current) => current ? {
        ...current,
        draft: { ...current.draft, images: [...current.draft.images, ...uploaded.urls].slice(0, 9) },
      } : current);
    } catch (error) {
      if (version === editorVersion.current) Alert.alert('图片上传失败', error instanceof Error ? error.message : '请重试');
    } finally {
      uploadPending.current = false;
      if (mounted.current) setUploading(false);
    }
  }

  async function recommendCategory() {
    if (!editor || recommending || mutationPending.current) return;
    const version = editorVersion.current;
    const request = ++categoryVersion.current;
    const { title, description } = editor.draft;
    if (!title.trim() || !description.trim()) {
      Alert.alert('提示', '请先填写标题和描述');
      return;
    }
    setRecommending(true);
    try {
      const result = await recommendMaterialCategory(title.trim(), description.trim());
      if (version !== editorVersion.current || request !== categoryVersion.current) return;
      setCandidates(result);
      if (!result.length) Alert.alert('暂无分类', '请完善标题和描述后重试');
    } catch (error) {
      if (version === editorVersion.current && request === categoryVersion.current) Alert.alert('推荐分类失败', error instanceof Error ? error.message : '请稍后重试');
    } finally {
      if (mounted.current && request === categoryVersion.current) setRecommending(false);
    }
  }

  function chooseCategory(candidate: MaterialCategoryCandidate) {
    if (!(candidate.cat_id || candidate.channel_cat_id || candidate.tb_cat_id)) {
      Alert.alert('分类不可用', '此分类没有有效平台标识，请重新推荐');
      return;
    }
    setEditor((current) => current ? {
      ...current,
      categoryChanged: true,
      draft: { ...current.draft, categoryName: categoryLabel(candidate), categoryCandidate: candidate },
    } : current);
    setCandidates([]);
  }

  async function save() {
    if (!editor || mutationPending.current || uploadPending.current || recommending) return;
    const version = editorVersion.current;
    const d = editor.draft;
    const title = d.title.trim();
    const description = d.description.trim();
    const price = Number(d.price);
    const originalPrice = d.originalPrice.trim() ? Number(d.originalPrice) : null;
    const quantity = Number(d.quantity);
    const postage = Number(d.postage || '0');
    const titleLimit = editor.id && editor.original?.title === d.title ? 200 : 30;
    if (!title || title.length > titleLimit) return Alert.alert('提示', '商品标题需为 1-30 字');
    if (!description || description.length > 1500) return Alert.alert('提示', '商品描述需为 1-1500 字');
    if (!Number.isFinite(price) || price <= 0) return Alert.alert('提示', '请输入有效价格');
    if (originalPrice !== null && (!Number.isFinite(originalPrice) || originalPrice < 0)) return Alert.alert('提示', '请输入有效原价');
    if (!d.images.length || d.images.length > 9) return Alert.alert('提示', '请上传 1-9 张商品图片');
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > 999999) return Alert.alert('提示', '库存需为 1-999999');
    if (!Number.isFinite(postage) || postage < 0 || postage > 1000) return Alert.alert('提示', '运费需为 0-1000 元');
    if (!editor.id && !d.categoryCandidate) return Alert.alert('提示', '请先推荐并选择商品分类');
    if (d.address.length > 200) return Alert.alert('提示', '宝贝所在地不能超过 200 字');

    const payload: MaterialInput = {
      title, description, price, original_price: originalPrice, images: d.images,
      quantity, shipping_method: d.shippingMethod,
      postage: d.shippingMethod === 'free' || d.shippingMethod === 'none' ? 0 : postage,
      address: d.address.trim() || null, condition: d.condition.trim() || '全新',
    };
    if (editor.categoryChanged && d.categoryCandidate) {
      const candidate = d.categoryCandidate;
      payload.category = d.categoryName;
      payload.platform_category_id = candidate.cat_id || null;
      payload.platform_category_name = candidate.cat_name || d.categoryName;
      payload.platform_channel_category_id = candidate.channel_cat_id || null;
      payload.platform_channel_category_name = candidate.channel_cat_name || d.categoryName;
      payload.platform_leaf_id = candidate.leaf_id || null;
      payload.platform_tb_category_id = candidate.tb_cat_id || null;
      payload.platform_category_path = candidate.path || [];
      payload.category_source = 'recommendation';
      payload.category_confidence = candidate.score ?? null;
      const original = editor.original;
      if (!original || original.platform_category_id !== payload.platform_category_id ||
          original.platform_channel_category_id !== payload.platform_channel_category_id ||
          original.platform_tb_category_id !== payload.platform_tb_category_id) {
        payload.platform_attributes = [];
      }
    }
    const changes = changedMaterialFields(editor, payload);
    if (editor.id && !Object.keys(changes).length) return Alert.alert('提示', '没有需要保存的修改');
    mutationPending.current = true;
    setSaving(true);
    try {
      if (editor.id) await updateMaterial(editor.id, changes);
      else await createMaterial(payload);
      if (version !== editorVersion.current) return;
      Alert.alert('成功', editor.id ? '素材已更新' : '素材已创建');
      if (fromPublish) router.back();
      else {
        setEditor(null);
        void loadPage(1);
      }
    } catch (error) {
      if (version === editorVersion.current) Alert.alert('保存失败', error instanceof Error ? error.message : '请稍后重试');
    } finally {
      mutationPending.current = false;
      if (mounted.current) setSaving(false);
    }
  }

  function confirmDelete(id: number, title: string) {
    if (mutationPending.current || uploadPending.current) return;
    const version = editorVersion.current;
    Alert.alert('删除素材', `确定删除「${title || '无标题'}」吗？此操作不可撤销。`, [
      { text: '取消', style: 'cancel' },
      { text: '删除', style: 'destructive', onPress: async () => {
        if (!mounted.current || version !== editorVersion.current || mutationPending.current) return;
        mutationPending.current = true;
        setDeleting(true);
        try {
          const detail = await getMaterial(id);
          if (!mounted.current || version !== editorVersion.current) return;
          if (detail.user_id !== userId) throw new Error('只能删除当前用户的素材');
          await deleteMaterial(id);
          if (!mounted.current || version !== editorVersion.current) return;
          if (editor?.id === id) {
            if (fromPublish) router.back();
            else setEditor(null);
          }
          void loadPage(1);
        } catch (error) {
          if (mounted.current) Alert.alert('删除失败', error instanceof Error ? error.message : '请稍后重试');
        } finally {
          mutationPending.current = false;
          if (mounted.current) setDeleting(false);
        }
      } },
    ]);
  }

  if (detailLoading) return <Loading label="加载素材详情..." />;

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: c.background }]} edges={['left', 'right', 'bottom']}>
      {editor ? (
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled" pointerEvents={saving || deleting ? 'none' : 'auto'}>
          <Text style={[styles.heading, { color: c.text }]}>{editor.id ? '素材详情与编辑' : '新建素材'}</Text>
          <Card style={styles.section}>
            <Text style={[styles.label, { color: c.text }]}>商品标题 *</Text>
            <Input value={editor.draft.title} onChangeText={(title) => updateDraft({ title })} maxLength={Math.max(30, editor.original?.title.length || 0)} placeholder="最多 30 字" />
            <Text style={[styles.label, { color: c.text }]}>商品描述 *</Text>
            <TextInput
              value={editor.draft.description}
              onChangeText={(description) => updateDraft({ description })}
              multiline maxLength={1500} textAlignVertical="top" placeholder="描述商品品牌、型号和成色"
              placeholderTextColor={c.textMuted}
              style={[styles.textArea, { color: c.text, backgroundColor: c.background, borderColor: c.border }]}
            />
            <Text style={[styles.label, { color: c.text }]}>分类 *</Text>
            <Text style={[styles.hint, { color: c.textSecondary }]}>{editor.draft.categoryName || '尚未选择分类'}</Text>
            <Button label="按标题和描述推荐分类" variant="secondary" onPress={() => { void recommendCategory(); }} loading={recommending} />
            {candidates.map((candidate, index) => (
              <Pressable key={`${candidate.cat_id}-${candidate.channel_cat_id}-${index}`} onPress={() => chooseCategory(candidate)} style={[styles.choice, { borderColor: c.border }]}>
                <Text style={[styles.label, { color: c.text }]}>{categoryLabel(candidate)}</Text>
                <Text style={[styles.hint, { color: c.textMuted }]}>{candidate.path?.map((part) => part.name).join(' / ')}</Text>
              </Pressable>
            ))}
          </Card>

          <Card style={styles.section}>
            <Text style={[styles.label, { color: c.text }]}>价格（元）*</Text>
            <Input value={editor.draft.price} onChangeText={(price) => updateDraft({ price })} keyboardType="decimal-pad" placeholder="0.00" />
            {editor.original?.sku_rows?.length ? <Text style={[styles.hint, { color: c.warning }]}>此素材有多规格价格；修改上方基础价格不会更改各规格价格。</Text> : null}
            <Text style={[styles.label, { color: c.text }]}>原价（可选）</Text>
            <Input value={editor.draft.originalPrice} onChangeText={(originalPrice) => updateDraft({ originalPrice })} keyboardType="decimal-pad" placeholder="0.00" />
            <Text style={[styles.label, { color: c.text }]}>库存</Text>
            <Input value={editor.draft.quantity} onChangeText={(quantity) => updateDraft({ quantity })} keyboardType="number-pad" />
            <Text style={[styles.label, { color: c.text }]}>成色</Text>
            <Input value={editor.draft.condition} onChangeText={(condition) => updateDraft({ condition })} maxLength={20} placeholder="全新" />
          </Card>

          <Card style={styles.section}>
            <Text style={[styles.label, { color: c.text }]}>商品图片 ({editor.draft.images.length}/9) *</Text>
            <View style={styles.imageRow}>
              {editor.draft.images.map((image, index) => (
                <View key={`${image}-${index}`} style={styles.imageBox}>
                  <Image source={{ uri: previewUrl(image, serverUrl || '') }} style={styles.image} />
                  <Pressable onPress={() => updateDraft({ images: editor.draft.images.filter((_, i) => i !== index) })} style={[styles.removeImage, { backgroundColor: c.error }]}>
                    <Text style={styles.removeText}>移除</Text>
                  </Pressable>
                </View>
              ))}
            </View>
            <Button label="选择并上传图片" variant="secondary" onPress={() => { void pickImages(); }} loading={uploading} disabled={editor.draft.images.length >= 9} />
          </Card>

          <Card style={styles.section}>
            <Text style={[styles.label, { color: c.text }]}>发货与所在地</Text>
            <View style={styles.shippingRow}>
              {SHIPPING_OPTIONS.map((option) => {
                const selected = editor.draft.shippingMethod === option.value;
                return (
                  <Pressable key={option.value} onPress={() => updateDraft({ shippingMethod: option.value })} style={[styles.shippingOption, { borderColor: selected ? c.primary : c.border, backgroundColor: selected ? c.primaryLight : c.surface }]}>
                    <Text style={[styles.hint, { color: selected ? c.primary : c.text }]}>{option.label}</Text>
                  </Pressable>
                );
              })}
            </View>
            {editor.draft.shippingMethod === 'template' ? <Text style={[styles.hint, { color: c.warning }]}>运费模板仅适用于鱼小铺账号；普通卖家请使用其他发货方式。</Text> : null}
            {editor.draft.shippingMethod !== 'free' && editor.draft.shippingMethod !== 'none' ? (
              <>
                <Text style={[styles.label, { color: c.text }]}>运费（元）</Text>
                <Input value={editor.draft.postage} onChangeText={(postage) => updateDraft({ postage })} keyboardType="decimal-pad" placeholder="0.00" />
              </>
            ) : null}
            <Text style={[styles.label, { color: c.text }]}>宝贝所在地（可选）</Text>
            <Input value={editor.draft.address} onChangeText={(address) => updateDraft({ address })} maxLength={200} placeholder="例如：浙江省 杭州市" />
            <Text style={[styles.hint, { color: c.textMuted }]}>批量发布时会由地址库分配所在地。</Text>
          </Card>

          <View style={styles.actions}>
            <Button label="取消" variant="secondary" onPress={closeEditor} disabled={saving || deleting} style={styles.action} />
            <Button label={editor.id ? '保存修改' : '创建素材'} onPress={() => { void save(); }} loading={saving} disabled={uploading || recommending || deleting} style={styles.action} />
          </View>
          {editor.id ? <Button label="删除素材" variant="danger" loading={deleting} disabled={saving || uploading} onPress={() => confirmDelete(editor.id!, editor.draft.title)} /> : null}
        </ScrollView>
      ) : (
        <ScrollView contentContainerStyle={styles.content} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { void loadPage(1); }} />}>
          <View style={styles.header}>
            <Text style={[styles.heading, { color: c.text }]}>素材库</Text>
            <Button label="新建素材" onPress={openNew} disabled={deleting} />
          </View>
          {loading ? <Loading label="加载素材..." /> : null}
          {loadError ? <EmptyState icon={Package} title="加载失败" message={loadError} error onRetry={() => { void loadPage(1); }} /> : null}
          {!loading && !loadError && !materials.length ? (
            <EmptyState icon={ImageIcon} title="暂无自己的素材" message={page * PAGE_SIZE < total ? '当前页没有自己的素材，请继续加载。' : '新建素材后即可在商品发布页选择。'} actionLabel="新建素材" onAction={openNew} />
          ) : null}
          {materials.map((material) => (
            <Card key={material.id} style={styles.materialCard}>
              <View style={styles.materialRow}>
                {material.images?.[0] ? <Image source={{ uri: previewUrl(material.images[0], serverUrl || '') }} style={styles.thumb} /> : <View style={[styles.thumb, { backgroundColor: c.surfaceAlt, alignItems: 'center', justifyContent: 'center' }]}><ImageIcon size={24} stroke={c.textMuted} /></View>}
                <View style={styles.materialBody}>
                  <Text style={[styles.materialTitle, { color: c.text }]} numberOfLines={2}>{material.title}</Text>
                  <Text style={[styles.hint, { color: c.primary }]}>¥{material.price}</Text>
                </View>
              </View>
              <View style={styles.actions}>
                <Button label="详情 / 编辑" variant="secondary" disabled={deleting} onPress={() => { void openEditor(material.id); }} style={styles.action} />
                <Button label="删除" variant="danger" disabled={deleting} onPress={() => confirmDelete(material.id, material.title)} style={styles.action} />
              </View>
            </Card>
          ))}
          {page * PAGE_SIZE < total ? <Button label="加载更多素材" variant="secondary" loading={loadingMore} disabled={refreshing || deleting} onPress={() => { void loadPage(page + 1, true); }} /> : null}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  content: { padding: spacing.lg, paddingBottom: spacing.xl * 2, gap: spacing.md },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md },
  heading: { ...typography.heading },
  section: { gap: spacing.sm },
  label: { ...typography.caption, fontWeight: '600' },
  hint: { ...typography.small },
  textArea: { ...typography.body, minHeight: 120, borderWidth: 1, borderRadius: radius.md, padding: spacing.md },
  choice: { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, gap: spacing.xs },
  imageRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  imageBox: { width: 84, gap: spacing.xs },
  image: { width: 84, height: 84, borderRadius: radius.sm },
  removeImage: { borderRadius: radius.sm, alignItems: 'center', paddingVertical: spacing.xs },
  removeText: { ...typography.small, color: '#FFFFFF' },
  shippingRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  shippingOption: { borderWidth: 1, borderRadius: radius.full, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  actions: { flexDirection: 'row', gap: spacing.sm },
  action: { flex: 1 },
  materialCard: { gap: spacing.md },
  materialRow: { flexDirection: 'row', gap: spacing.md },
  materialBody: { flex: 1, gap: spacing.xs },
  materialTitle: { ...typography.body, fontWeight: '600' },
  thumb: { width: 64, height: 64, borderRadius: radius.sm },
});
