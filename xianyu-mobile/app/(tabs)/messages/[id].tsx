import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TextInput,
  Pressable,
  KeyboardAvoidingView,
  Platform,
  Image,
  Modal,
  TouchableOpacity,
  Alert,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useLocalSearchParams } from 'expo-router';
import { useColorScheme } from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { WebView } from 'react-native-webview';
import {
  Image as ImageIcon,
  Video,
  Play,
  MessageSquareText,
  Plus,
  ShoppingBag,
  Trash2,
  X,
} from 'lucide-react-native';
import { OrdersPanel } from '@/components/OrdersPanel';
import { BlacklistButton } from '@/components/BlacklistButton';
import { Loading, Button, Input } from '@/components/ui';
import { colors, spacing, typography, radius } from '@/lib/theme';
import { wsManager } from '@/lib/ws';
import { useConfigStore } from '@/stores/config';
import {
  getMessages,
  getChatAccounts,
  getChatUserInfos,
  sendMessage,
  sendImageMessage,
  sendVideoMessage,
  recallMessage,
  getQuickPhrases,
  createQuickPhrase,
  updateQuickPhrase,
  deleteQuickPhrase,
  type ChatMessage,
  type QuickPhrase,
} from '@/api/wrappers/chat';

/** 消息撤回时间窗口（2 分钟） */
const RECALL_WINDOW_MS = 2 * 60 * 1000;

/** 本地乐观消息的 ID 前缀：这类消息尚未取得平台 messageId */
const LOCAL_MSG_PREFIX = 'local-';

/**
 * 本地乐观占位被真实回声吸收的时间窗口
 *
 * 仅用于“自己刚发的那条还没拿到平台 ID”的场景。窗口内的判断同时要求
 * 同向、同类型、同文本，且**只删除本地占位**：真实消息一定保留，
 * 因此连发两条相同内容时不会误合并（它们各自带不同的平台 ID）。
 */
const LOCAL_ECHO_WINDOW_MS = 5000;

/** 判定是否尚未获取平台 ID 的本地乐观消息 */
function isLocalMessage(msg: ChatMessage): boolean {
  return !msg.messageId || msg.messageId.startsWith(LOCAL_MSG_PREFIX);
}

/**
 * 判定 local 是否是 real 的本地占位
 *
 * 只认“自己 + 同类型 + 同文本 + 时间接近”，且 local 必须没有平台 ID。
 * 两条真实消息永远互不吸收——它们各自带不同的平台 ID，
 * 所以连续发送两条相同内容不会丢消息。
 */
function isEchoOf(local: ChatMessage, real: ChatMessage): boolean {
  return isLocalMessage(local) === true
    && isLocalMessage(real) === false
    && local.isSelf
    && real.isSelf
    && !local.failed
    && !real.failed
    && local.type === real.type
    && local.text === real.text
    // 本地文件 URI 与 CDN URL 无法靠空文本关联，等待明确回执。
    && local.type !== 'video'
    && (local.type !== 'image' || (local.images.length > 0
      && JSON.stringify(local.images) === JSON.stringify(real.images)))
    && Math.abs(local.time - real.time) < LOCAL_ECHO_WINDOW_MS;
}

/**
 * 按稳定 messageId 合并消息列表
 *
 * 去重键为平台 messageId。本地乐观占位（尚无平台 ID）允许被同内容的
 * 真实回声原地替换，避免自己刚发的消息同时出现“本地一条 + 回声一条”。
 *
 * 吸收只发生在 local→real 方向，一个新平台 ID 至多替换一个占位，
 * 最终按消息时间稳定排序。吸收失败最多多显示一条本地占位，
 * 不会丢失真实消息，属于安全方向的降级。
 */
function mergeMessages(existing: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  const result: ChatMessage[] = [];
  const seenIds = new Set<string>();
  for (const msg of existing) {
    if (msg.messageId && seenIds.has(msg.messageId)) continue;
    if (msg.messageId) seenIds.add(msg.messageId);
    result.push(msg);
  }
  for (const msg of incoming) {
    if (msg.messageId && seenIds.has(msg.messageId)) continue;
    if (msg.messageId) seenIds.add(msg.messageId);
    if (!isLocalMessage(msg)) {
      // 每个新平台 ID 至多替换一个占位；重复回声不能再次消费另一个占位。
      const index = result.findIndex((local) => isEchoOf(local, msg));
      if (index >= 0) {
        result[index] = msg;
        continue;
      }
    }
    result.push(msg);
  }
  return result.sort((a, b) => a.time - b.time);
}

/** 用发送回执精确替换本地占位；回声已到达时只移除该占位。 */
function applySendReceipt(existing: ChatMessage[], localId: string, receipt: { messageId?: string; imageUrl?: string; videoUrl?: string; videoCoverUrl?: string }): ChatMessage[] {
  if (!receipt.messageId) return existing;
  const local = existing.find((msg) => msg.messageId === localId);
  if (!local) return existing;
  const rest = existing.filter((msg) => msg.messageId !== localId);
  if (rest.some((msg) => msg.messageId === receipt.messageId)) return rest;
  return [...rest, {
    ...local, messageId: receipt.messageId, sending: false, failed: false, failReason: undefined,
    images: receipt.imageUrl ? [receipt.imageUrl] : local.images,
    videoUrl: receipt.videoUrl || local.videoUrl,
    videoCoverUrl: receipt.videoCoverUrl || local.videoCoverUrl,
  }].sort((a, b) => a.time - b.time);
}

/** 距底部多少像素内仍视为“贴底”，用于决定新消息是否自动滚动 */
const BOTTOM_THRESHOLD_PX = 80;
const MAX_VIDEO_BYTES = 20 * 1024 * 1024;

function avatarInitial(name?: string, id?: string): string {
  return (name || id || '?').trim().charAt(0).toUpperCase() || '?';
}

function BuyerAvatar({ uri, name, userId, color }: { uri?: string; name?: string; userId?: string; color: string }) {
  const url = uri?.trim() || '';
  const source = url.startsWith('//') ? `https:${url}` : url;
  const [failedUri, setFailedUri] = useState('');
  return (
    <View style={[styles.msgAvatar, { backgroundColor: color }]}>
      {source && source !== failedUri ? (
        <Image source={{ uri: source }} style={styles.msgAvatar} onError={() => setFailedUri(source)} />
      ) : (
        <Text style={styles.msgAvatarText}>{avatarInitial(name, userId)}</Text>
      )}
    </View>
  );
}

/** 沿用 Web 端已有媒体代理，本地文件不经过服务器。 */
function chatVideoUrl(uri: string, serverUrl: string | null): string {
  const url = uri.startsWith('//') ? `https:${uri}` : uri;
  const base = serverUrl?.replace(/\/+$/, '') || '';
  if (!base) return url;
  if (url.startsWith('/api/')) return `${base}${url}`;
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (['dingtalk.cn', 'dingtalk.com'].some((domain) => host === domain || host.endsWith(`.${domain}`))) {
      return `${base}/api/v1/chat-new/video-proxy?url=${encodeURIComponent(url)}`;
    }
    const cdnHosts = ['img.alicdn.com', 'gw.alicdn.com', 'g.alicdn.com', 'img.taobao.com', 'goofish.com',
      'goofish-prod.oss-cn-hangzhou.aliyuncs.com', 'img01.taobaocdn.com', 'img02.taobaocdn.com',
      'img03.taobaocdn.com', 'img04.taobaocdn.com', 'img05.taobaocdn.com', 'cbu01.alicdn.com'];
    if (cdnHosts.some((domain) => host === domain || host.endsWith(`.${domain}`))) {
      return `${base}/api/v1/chat-new/image-proxy?url=${encodeURIComponent(url)}`;
    }
  } catch {
    // file/content URI 不需要 CDN 代理。
  }
  return url;
}

function videoHtml(uri: string, poster?: string): string {
  const escape = (value: string) => value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>html,body{margin:0;height:100%;background:#000;overflow:hidden}video{width:100%;height:100%;object-fit:contain}</style></head><body><video src="${escape(uri)}"${poster ? ` poster="${escape(poster)}"` : ''} controls playsinline preload="metadata" onerror="window.ReactNativeWebView.postMessage('video-error')"></video></body></html>`;
}

/** 留在详情模块内，避免 Expo Router 把组件注册为独立页面。 */
function ChatVideoPlayer({ uri, poster, onLongPress }: { uri: string; poster?: string; onLongPress: () => void }) {
  const serverUrl = useConfigStore((state) => state.serverUrl);
  const [open, setOpen] = useState(false);
  const [playbackFailed, setPlaybackFailed] = useState(false);
  const [failedPoster, setFailedPoster] = useState('');
  const videoUrl = chatVideoUrl(uri, serverUrl);
  const coverUrl = poster ? chatVideoUrl(poster, serverUrl) : '';
  const localBase = uri.startsWith('file://') ? uri.slice(0, uri.lastIndexOf('/') + 1) : undefined;
  const source = useMemo(() => ({
    html: videoHtml(videoUrl, coverUrl),
    baseUrl: localBase || serverUrl || undefined,
  }), [videoUrl, coverUrl, localBase, serverUrl]);

  useEffect(() => { setPlaybackFailed(false); }, [videoUrl]);

  return (
    <>
      <Pressable
        style={styles.videoPreview}
        accessibilityRole="button"
        accessibilityLabel="播放视频消息"
        onLongPress={onLongPress}
        delayLongPress={400}
        onPress={() => { setPlaybackFailed(false); setOpen(true); }}
      >
        {coverUrl && failedPoster !== coverUrl ? (
          <Image source={{ uri: coverUrl }} style={StyleSheet.absoluteFill} resizeMode="cover" onError={() => setFailedPoster(coverUrl)} />
        ) : <Video size={36} color="#FFF" />}
        <View style={styles.videoPlayBadge}>
          <Play size={18} color="#FFF" />
          <Text style={styles.videoCaption}>点击播放</Text>
        </View>
      </Pressable>
      <Modal visible={open} animationType="fade" onRequestClose={() => setOpen(false)}>
        <SafeAreaView style={styles.videoModal}>
          <Pressable accessibilityLabel="关闭视频" style={styles.videoClose} onPress={() => setOpen(false)}>
            <X size={28} color="#FFF" />
          </Pressable>
          {open && !playbackFailed ? (
            <WebView
              key={videoUrl}
              source={source}
              style={styles.videoWebView}
              originWhitelist={['*']}
              javaScriptEnabled
              allowsInlineMediaPlayback
              allowsFullscreenVideo
              mediaPlaybackRequiresUserAction
              allowFileAccess={!!localBase}
              allowFileAccessFromFileURLs={!!localBase}
              allowingReadAccessToURL={localBase}
              mixedContentMode="compatibility"
              onShouldStartLoadWithRequest={(request) => request.url === 'about:blank' || request.url === source.baseUrl || request.url === videoUrl}
              onError={() => setPlaybackFailed(true)}
              onHttpError={() => setPlaybackFailed(true)}
              onMessage={(event) => { if (event.nativeEvent.data === 'video-error') setPlaybackFailed(true); }}
            />
          ) : (
            <View style={styles.videoError}>
              <Text style={styles.videoCaption}>视频暂时无法播放，请检查网络或视频格式</Text>
              <Pressable onPress={() => setPlaybackFailed(false)} style={styles.videoClose}>
                <Text style={styles.videoCaption}>重新加载</Text>
              </Pressable>
            </View>
          )}
        </SafeAreaView>
      </Modal>
    </>
  );
}

export default function ChatDetailScreen() {
  const scheme = useColorScheme();
  const c = colors[scheme === 'dark' ? 'dark' : 'light'];
  const { id, account_id, name, buyer_id, avatar, raw_cid } = useLocalSearchParams<{
    id: string;
    account_id: string;
    name: string;
    buyer_id: string;
    avatar?: string;
    raw_cid?: string;
  }>();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputText, setInputText] = useState('');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  // hasMore 必须是 state：只存在 ref 里时“加载更早的消息”入口不会随分页耗尽消失
  const [hasMore, setHasMore] = useState(true);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const [showOrders, setShowOrders] = useState(false);
  // 当前会话所属账号的展示名（多账号下用于确认在回复哪个号）
  const [accountLabel, setAccountLabel] = useState('');
  const [buyerInfo, setBuyerInfo] = useState<{ accountId: string; cid: string; avatar: string; nick: string } | null>(null);
  const currentBuyer = buyerInfo?.accountId === account_id && buyerInfo.cid === id ? buyerInfo : null;
  const buyerAvatar = avatar || currentBuyer?.avatar;
  const buyerName = currentBuyer?.nick || name;

  useEffect(() => {
    if (!account_id || !id || !buyer_id || (avatar && name && name !== buyer_id && name !== '未知用户')) return;
    let active = true;
    getChatUserInfos(account_id, [{ userId: buyer_id, cid: raw_cid || id }]).then((infos) => {
      if (!active) return;
      const info = infos[buyer_id];
      if (info) setBuyerInfo({ accountId: account_id, cid: id, avatar: info.avatar, nick: info.nick });
    }).catch(() => { /* 资料不可用时继续显示占位，不阻塞聊天。 */ });
    return () => { active = false; };
  }, [account_id, id, buyer_id, avatar, name, raw_cid]);

  // 快捷短语
  const [phrases, setPhrases] = useState<QuickPhrase[]>([]);
  const [phrasesLoading, setPhrasesLoading] = useState(false);
  const [showPhrases, setShowPhrases] = useState(false);
  const [phraseModalVisible, setPhraseModalVisible] = useState(false);
  const [editingPhrase, setEditingPhrase] = useState<QuickPhrase | null>(null);
  const [phraseTitle, setPhraseTitle] = useState('');
  const [phraseContent, setPhraseContent] = useState('');
  const [savingPhrase, setSavingPhrase] = useState(false);

  // 消息撤回操作菜单
  const [recallTarget, setRecallTarget] = useState<ChatMessage | null>(null);
  const [recalling, setRecalling] = useState(false);

  const listRef = useRef<FlatList>(null);
  // 头部插入历史消息时保持阅读位置（onContentSizeChange 不滚到底部）
  const prependingRef = useRef(false);
  const cursorRef = useRef<number | null>(null);
  const hasMoreRef = useRef(true);
  // 头部插入历史消息的并发锁（同步 ref，state 异步更新拦不住快速二次触发）
  const loadingMoreRef = useRef(false);
  // 用户是否贴底：上翻查看历史时不能因为新消息被强行拉回底部
  const atBottomRef = useRef(true);
  // 首次布局时直接跳到底部，避免长历史从顶部滚动下来的闪动
  const didInitialScrollRef = useRef(false);
  const videoSendingRef = useRef(false);
  const videoScopeRef = useRef({ accountId: account_id, cid: id });
  useEffect(() => {
    const scope = { accountId: account_id, cid: id };
    videoScopeRef.current = scope;
    if (videoSendingRef.current) setSending(false);
    videoSendingRef.current = false;
    return () => {
      if (videoScopeRef.current === scope) videoScopeRef.current = { accountId: '', cid: '' };
    };
  }, [account_id, id]);

  const loadMessages = useCallback(
    async (append: boolean) => {
      if (!account_id || !id) return;
      if (append && !hasMoreRef.current) return;
      // 头部插入防抖：用同步 ref 拦截并发，避免在 cursor 更新前重复触发导致同一页历史被预插两遍
      if (append && loadingMoreRef.current) return;

      try {
        if (!append) setLoading(true);
        else {
          setLoadingMore(true);
          loadingMoreRef.current = true;
          // 标记本次是头部插入历史消息，onContentSizeChange 时保持阅读位置不滚底
          prependingRef.current = true;
        }

        const resp = await getMessages(
          account_id,
          id,
          append ? cursorRef.current : null,
        );

        if (append) {
          // 历史分页：更早的消息排在前面，重复项按稳定 ID 去重
          setMessages((prev) => mergeMessages(resp.messages, prev));
        } else {
          // 首屏/刷新：以服务端最新页为主，同时吸收本地占位与加载期间到达的推送，
          // 不能整体替换，否则会冲掉刚乐观添加的发送中消息
          setMessages((prev) => mergeMessages(prev, resp.messages));
        }
        cursorRef.current = resp.nextCursor;
        hasMoreRef.current = resp.hasMore;
        setHasMore(resp.hasMore);
      } catch (e) {
        console.error('加载消息失败', e);
        prependingRef.current = false; // 出错时复位，避免卡死
      } finally {
        // 复位 loadingMore 同步锁
        loadingMoreRef.current = false;
        setLoading(false);
        setLoadingMore(false);
        // prependingRef 仅在"头部插入且响应为空"时在此复位（onContentSizeChange 不会触发）；
        // 非空时交由 onContentSizeChange 复位以保持阅读位置；加 400ms 兜底定时器防卡死
        if (append) {
          setTimeout(() => { prependingRef.current = false; }, 400);
        }
      }
    },
    [account_id, id],
  );

  useEffect(() => {
    loadMessages(false);
  }, [loadMessages]);

  // 设置当前活跃会话（用于 WS 消息时判断是否计未读）
  useEffect(() => {
    wsManager.setActiveCid(id);
    return () => wsManager.setActiveCid(null);
  }, [id]);

  // 解析当前账号展示名：优先备注名，退回显示名，最后用 ID
  useEffect(() => {
    if (!account_id) {
      setAccountLabel('');
      return;
    }
    let cancelled = false;
    getChatAccounts()
      .then((list) => {
        if (cancelled) return;
        const match = list.find((a) => a.account_id === account_id);
        setAccountLabel(match ? match.remark || match.display_name || account_id : account_id);
      })
      .catch(() => {
        if (!cancelled) setAccountLabel(account_id);
      });
    return () => {
      cancelled = true;
    };
  }, [account_id]);

  // 订阅 WebSocket 实时消息
  useEffect(() => {
    if (!account_id || !id) return;
    const unsub = wsManager.onMessage((accountId, cid, message) => {
      if (accountId !== account_id || cid !== id) return;
      // 按稳定 messageId 合并：自己发的消息已通过乐观更新加入，回声到达时替换占位而非重复追加
      setMessages((prev) => mergeMessages(prev, [message]));
    });
    return unsub;
  }, [account_id, id]);

  /**
   * 断线重连 / 前台恢复后补拉
   *
   * 断连期间的推送会永久丢失，仅靠 WS 心跳无法发现上游 IM 掉线，
   * 因此每次连接恢复都重新对齐一次本会话的最新一页消息。
   */
  const syncLatest = useCallback(async () => {
    if (!account_id || !id) return;
    try {
      const resp = await getMessages(account_id, id, null);
      // 不触碰 cursorRef / hasMoreRef：补拉只对齐最新页，不能影响历史分页位置
      setMessages((prev) => mergeMessages(prev, resp.messages));
    } catch (e) {
      console.error('补拉最新消息失败', e);
    }
  }, [account_id, id]);

  useEffect(() => {
    if (!account_id) return;
    const unsub = wsManager.onReconnected((accountId) => {
      if (accountId !== account_id) return;
      syncLatest();
    });
    return unsub;
  }, [account_id, syncLatest]);

  // 加载快捷短语
  const loadPhrases = useCallback(async () => {
    setPhrasesLoading(true);
    try {
      const list = await getQuickPhrases();
      setPhrases(list);
    } catch (e) {
      console.error('加载快捷短语失败', e);
    } finally {
      setPhrasesLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPhrases();
  }, [loadPhrases]);

  /** 标记某条乐观消息为发送失败 */
  function markFailed(messageId: string, reason: string) {
    setMessages((prev) =>
      prev.map((m) =>
        m.messageId === messageId ? { ...m, sending: false, failed: true, failReason: reason } : m,
      ),
    );
  }

  async function handleSend() {
    if (!inputText.trim() || !account_id || !id || !buyer_id || sending || videoSendingRef.current) return;
    const text = inputText.trim();
    setInputText('');
    setSending(true);

    const optimisticMsg: ChatMessage = {
      messageId: `local-${Date.now()}`,
      senderId: 'self',
      senderName: '我',
      isSelf: true,
      type: 'text',
      text,
      images: [],
      time: Date.now(),
    };
    setMessages((prev) => [...prev, optimisticMsg]);

    try {
      const res = await sendMessage(account_id, id, buyer_id, text);
      if (!res.success) markFailed(optimisticMsg.messageId, res.message || '发送失败');
      else if (res.data) setMessages((prev) => applySendReceipt(prev, optimisticMsg.messageId, res.data!));
    } catch (e) {
      markFailed(optimisticMsg.messageId, (e as Error).message);
    } finally {
      setSending(false);
    }
  }

  /** 发送一条文本内容（用于快捷短语） */
  async function handleSendPhrase(content: string) {
    const text = content.trim();
    if (!text || !account_id || !id || !buyer_id || sending || videoSendingRef.current) return;
    setSending(true);

    const optimisticMsg: ChatMessage = {
      messageId: `local-${Date.now()}`,
      senderId: 'self',
      senderName: '我',
      isSelf: true,
      type: 'text',
      text,
      images: [],
      time: Date.now(),
    };
    setMessages((prev) => [...prev, optimisticMsg]);

    try {
      const res = await sendMessage(account_id, id, buyer_id, text);
      if (!res.success) markFailed(optimisticMsg.messageId, res.message || '发送失败');
      else if (res.data) setMessages((prev) => applySendReceipt(prev, optimisticMsg.messageId, res.data!));
    } catch (e) {
      markFailed(optimisticMsg.messageId, (e as Error).message);
    } finally {
      setSending(false);
    }
  }

  /** 选择并发送图片 */
  async function handleImagePick() {
    if (!account_id || !id || !buyer_id || sending || videoSendingRef.current) return;

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsEditing: false,
      quality: 0.8,
    });
    if (result.canceled || !result.assets || result.assets.length === 0) return;

    const asset = result.assets[0];
    const uri = asset.uri;
    setSending(true);

    const optimisticMsg: ChatMessage = {
      messageId: `local-img-${Date.now()}`,
      senderId: 'self',
      senderName: '我',
      isSelf: true,
      type: 'image',
      text: '',
      images: [uri],
      time: Date.now(),
    };
    setMessages((prev) => [...prev, optimisticMsg]);

    try {
      const receipt = await sendImageMessage(account_id, id, buyer_id, uri);
      setMessages((prev) => applySendReceipt(prev, optimisticMsg.messageId, receipt));
    } catch (e) {
      markFailed(optimisticMsg.messageId, (e as Error).message);
    } finally {
      setSending(false);
    }
  }

  /** 选择并发送视频：先显示本地乐观消息，再等待上传和 IM 回执。 */
  async function handleVideoPick() {
    if (!account_id || !id || !buyer_id || sending || videoSendingRef.current) return;
    const scope = videoScopeRef.current;
    const isCurrent = () => videoScopeRef.current === scope;
    videoSendingRef.current = true;
    setSending(true);
    let localId: string | undefined;
    try {
      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!isCurrent()) return;
      if (!permission.granted) {
        Alert.alert('需要相册权限', '请在系统设置中允许访问相册后选择视频');
        return;
      }
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['videos'],
        allowsEditing: false,
      });
      if (!isCurrent() || result.canceled || !result.assets?.length) return;
      const asset = result.assets[0];
      if (asset.type !== 'video') throw new Error('请选择视频文件');
      if (asset.fileSize === 0) throw new Error('视频文件为空');
      if (asset.fileSize != null && asset.fileSize > MAX_VIDEO_BYTES) throw new Error('视频大小不能超过20MB');
      localId = `local-video-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const optimisticMsg: ChatMessage = {
        messageId: localId, senderId: 'self', senderName: '我', isSelf: true,
        type: 'video', text: '', images: [], videoUrl: asset.uri, time: Date.now(), sending: true,
      };
      setMessages((prev) => isCurrent() ? [...prev, optimisticMsg] : prev);
      const receipt = await sendVideoMessage(
        scope.accountId,
        scope.cid,
        buyer_id,
        asset.uri,
        asset.fileName || undefined,
        asset.mimeType || undefined,
      );
      if (isCurrent()) setMessages((prev) => isCurrent() ? applySendReceipt(prev, optimisticMsg.messageId, receipt) : prev);
    } catch (e) {
      if (!isCurrent()) return;
      const reason = e instanceof Error ? e.message : '视频发送失败';
      if (localId) markFailed(localId, reason);
      else Alert.alert('无法发送视频', reason);
    } finally {
      if (isCurrent()) {
        videoSendingRef.current = false;
        setSending(false);
      }
    }
  }

  /** 长按自己的消息：弹出撤回操作菜单 */
  function handleMessageLongPress(message: ChatMessage) {
    // 仅自己发送的、非系统、未失败的消息可撤回
    if (!message.isSelf || message.type === 'system' || message.failed || isLocalMessage(message)) return;
    if (Date.now() - message.time >= RECALL_WINDOW_MS) {
      Alert.alert('提示', '该消息已超过 2 分钟，无法撤回');
      return;
    }
    setRecallTarget(message);
  }

  /** 执行撤回 */
  async function handleRecall() {
    const target = recallTarget;
    if (!target || !account_id || recalling) return;
    setRecalling(true);
    try {
      await recallMessage(account_id, target.messageId, target.time);
      setMessages((prev) =>
        prev.map((m) =>
          m.messageId === target.messageId
            ? { ...m, type: 'system', text: '你撤回了一条消息', images: [], videoUrl: undefined, videoCoverUrl: undefined }
            : m,
        ),
      );
      setRecallTarget(null);
    } catch (e) {
      Alert.alert('撤回失败', (e as Error).message);
    } finally {
      setRecalling(false);
    }
  }

  /** 打开快捷短语编辑/新建弹窗 */
  function openPhraseEditor(phrase?: QuickPhrase) {
    setEditingPhrase(phrase ?? null);
    setPhraseTitle(phrase?.title ?? '');
    setPhraseContent(phrase?.content ?? '');
    setPhraseModalVisible(true);
  }

  /** 长按快捷短语：编辑/删除菜单 */
  function handlePhraseLongPress(phrase: QuickPhrase) {
    Alert.alert(phrase.title, undefined, [
      { text: '编辑', onPress: () => openPhraseEditor(phrase) },
      {
        text: '删除',
        style: 'destructive',
        onPress: () => handleDeletePhrase(phrase),
      },
      { text: '取消', style: 'cancel' },
    ]);
  }

  /** 保存（新建或更新）快捷短语 */
  async function savePhrase() {
    const title = phraseTitle.trim();
    const content = phraseContent.trim();
    if (!title || !content || savingPhrase) return;
    setSavingPhrase(true);
    try {
      if (editingPhrase) {
        await updateQuickPhrase(editingPhrase.id, title, content);
      } else {
        await createQuickPhrase(title, content);
      }
      setPhraseModalVisible(false);
      await loadPhrases();
    } catch (e) {
      Alert.alert('保存失败', (e as Error).message);
    } finally {
      setSavingPhrase(false);
    }
  }

  /** 删除快捷短语 */
  async function handleDeletePhrase(phrase: QuickPhrase) {
    Alert.alert('删除快捷短语', `确定删除"${phrase.title}"吗？`, [
      { text: '取消', style: 'cancel' },
      {
        text: '删除',
        style: 'destructive',
        onPress: async () => {
          try {
            await deleteQuickPhrase(phrase.id);
            await loadPhrases();
          } catch (e) {
            Alert.alert('删除失败', (e as Error).message);
          }
        },
      },
    ]);
  }

  function formatTime(ts: number): string {
    if (!ts) return '';
    const d = new Date(ts);
    return `${d.getHours().toString().padStart(2, '0')}:${d
      .getMinutes()
      .toString()
      .padStart(2, '0')}`;
  }

  // 消息项渲染（useCallback 稳定引用，避免 WS 高频消息导致全列表重渲染）
  const renderMessage = useCallback(
    ({ item }: { item: ChatMessage }) => (
      <Pressable
        onLongPress={() => handleMessageLongPress(item)}
        delayLongPress={400}
        style={[styles.msgRow, item.isSelf ? styles.msgRowSelf : styles.msgRowOther]}
      >
        {!item.isSelf && <BuyerAvatar uri={item.senderAvatar || buyerAvatar} name={buyerName || item.senderName} userId={buyer_id || item.senderId} color={c.primary} />}
        <View
          style={[
            styles.msgBubble,
            {
              backgroundColor: item.isSelf ? c.primary : c.surface,
              borderColor: c.border,
            },
          ]}
        >
          {(item.type === 'text' || item.type === 'card') && (
            <Text style={[styles.msgText, { color: item.isSelf ? '#FFF' : c.text }]}>
              {item.text || (item.type === 'card' ? '[卡片]' : '')}
            </Text>
          )}
          {item.type === 'image' && item.images.length > 0 && (
            <TouchableOpacity
              onPress={() => item.images[0] && setPreviewImage(item.images[0])}
            >
              <Image
                source={{ uri: item.images[0] }}
                style={styles.msgImage}
                resizeMode="cover"
              />
            </TouchableOpacity>
          )}
          {item.type === 'video' && item.videoUrl && (
            <ChatVideoPlayer uri={item.videoUrl} poster={item.videoCoverUrl} onLongPress={() => handleMessageLongPress(item)} />
          )}
          {item.type === 'video' && !item.videoUrl && (
            <Text style={[styles.msgText, { color: item.isSelf ? '#FFF' : c.text }]}>{item.text || '[视频暂不可用]'}</Text>
          )}
          {item.type === 'system' && (
            <Text style={[styles.msgSystem, { color: c.textMuted }]}>{item.text}</Text>
          )}
          {item.failed && (
            <Text style={[styles.msgFailed, { color: c.error }]}>
              ⚠ {item.failReason || '发送失败'}
            </Text>
          )}
          {item.type === 'video' && item.isSelf && !item.failed && (
            <Text style={[styles.msgFailed, { color: '#FFF' }]}>{item.sending ? '视频发送中...' : '已发送'}</Text>
          )}
        </View>
      </Pressable>
    ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [id, account_id, buyerName, buyer_id, buyerAvatar, c.primary, c.surface, c.border, c.text, c.textMuted, c.error, recalling],
  );

  if (loading) {
    return (
      <SafeAreaView style={[styles.container, { backgroundColor: c.background }]}>
        <Loading label="加载消息..." />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: c.background }]} edges={['bottom']}>
      <KeyboardAvoidingView
        style={styles.container}
        // Android 依赖 windowSoftInputMode=adjustResize 自适应，显式设置 behavior
        // 会与系统调整叠加导致输入栏被顶出屏幕，故保持 undefined
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}
      >
        {/* 聊天头部：买家名 + 所属账号 + 黑名单 */}
        <View style={[styles.chatHeader, { backgroundColor: c.surface, borderBottomColor: c.border }]}>
          <View style={styles.chatHeaderMain}>
            <BuyerAvatar uri={buyerAvatar} name={buyerName} userId={buyer_id} color={c.primary} />
            <Text style={[styles.chatHeaderName, { color: c.text }]} numberOfLines={1}>
              {buyerName || '聊天'}
            </Text>
            {/* 多账号下必须能看出当前回复的是哪个账号，否则容易回错号 */}
            {accountLabel ? (
              <View style={[styles.accountTag, { backgroundColor: c.surfaceAlt, borderColor: c.border }]}>
                <Text style={[styles.accountTagText, { color: c.textSecondary }]} numberOfLines={1}>
                  {accountLabel}
                </Text>
              </View>
            ) : null}
          </View>
          {account_id && id && (
            <BlacklistButton accountId={account_id} cid={id} />
          )}
        </View>

        {hasMore && messages.length > 0 && (
          <Pressable
            onPress={() => loadMessages(true)}
            disabled={loadingMore}
            style={styles.loadMoreBar}
          >
            <Text style={[styles.loadMoreText, { color: loadingMore ? c.textMuted : c.primary }]}>
              {loadingMore ? '加载中...' : '加载更早的消息'}
            </Text>
          </Pressable>
        )}

        <FlatList
          ref={listRef}
          data={messages}
          keyExtractor={(item) => item.messageId}
          renderItem={renderMessage}
          // 聊天消息频繁追加，保留稍大的渲染窗口保证滚动流畅
          windowSize={11}
          contentContainerStyle={styles.msgList}
          onScroll={(e) => {
            const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
            const distanceToBottom =
              contentSize.height - contentOffset.y - layoutMeasurement.height;
            atBottomRef.current = distanceToBottom <= BOTTOM_THRESHOLD_PX;
          }}
          scrollEventThrottle={16}
          // 键盘弹起时把最新消息顶到可见区域，否则输入时看不到刚发的消息
          onLayout={() => {
            if (!didInitialScrollRef.current && messages.length > 0) {
              didInitialScrollRef.current = true;
              listRef.current?.scrollToEnd({ animated: false });
            }
          }}
          onContentSizeChange={() => {
            if (prependingRef.current) {
              // 历史消息头部插入完成，保持当前阅读位置
              prependingRef.current = false;
              return;
            }
            // 仅在用户贴底时跟随新消息；上翻查看历史时不能被强行拉回底部
            if (atBottomRef.current) {
              listRef.current?.scrollToEnd({ animated: true });
            }
          }}
          ListEmptyComponent={
            <View style={styles.empty}>
              <Text style={[styles.emptyText, { color: c.textMuted }]}>
                暂无消息，发送第一条消息吧
              </Text>
            </View>
          }
        />

        {/* 快捷短语面板 */}
        {showPhrases && (
          <View
            style={[styles.phrasePanel, { backgroundColor: c.surface, borderTopColor: c.border }]}
          >
            {phrasesLoading && phrases.length === 0 ? (
              <Text style={[styles.phraseEmpty, { color: c.textMuted }]}>加载中...</Text>
            ) : phrases.length === 0 ? (
              <Pressable
                style={[styles.phraseAddFirst, { borderColor: c.border }]}
                onPress={() => openPhraseEditor()}
              >
                <Plus size={16} color={c.primary} />
                <Text style={[styles.phraseAddFirstText, { color: c.primary }]}>
                  添加快捷短语
                </Text>
              </Pressable>
            ) : (
              <FlatList
                horizontal
                style={styles.phraseScroll}
                data={phrases}
                keyExtractor={(p) => String(p.id)}
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={styles.phraseList}
                ListFooterComponent={
                  <Pressable
                    style={[styles.phraseAddChip, { borderColor: c.border }]}
                    onPress={() => openPhraseEditor()}
                  >
                    <Plus size={16} color={c.textSecondary} />
                  </Pressable>
                }
                renderItem={({ item: p }) => (
                  <TouchableOpacity
                    style={[styles.phraseChip, { backgroundColor: c.background, borderColor: c.border }]}
                    onPress={() => handleSendPhrase(p.content)}
                    onLongPress={() => handlePhraseLongPress(p)}
                    delayLongPress={400}
                  >
                    <Text style={[styles.phraseChipTitle, { color: c.text }]} numberOfLines={1}>
                      {p.title}
                    </Text>
                    <Text style={[styles.phraseChipContent, { color: c.textMuted }]} numberOfLines={1}>
                      {p.content}
                    </Text>
                  </TouchableOpacity>
                )}
              />
            )}
          </View>
        )}

        <View style={[styles.actionBar, { backgroundColor: c.surface, borderTopColor: c.border }]}>
          {/* 图片发送按钮 */}
          <Pressable
            onPress={handleImagePick}
            disabled={sending}
            style={({ pressed }) => [
              styles.iconBtn,
              { opacity: pressed || sending ? 0.5 : 1 },
            ]}
          >
            <ImageIcon size={24} color={c.text} />
          </Pressable>

          {/* 视频发送按钮 */}
          <Pressable
            onPress={handleVideoPick}
            accessibilityLabel="选择并发送视频"
            disabled={sending}
            style={({ pressed }) => [styles.iconBtn, { opacity: pressed || sending ? 0.5 : 1 }]}
          >
            <Video size={24} color={c.text} />
          </Pressable>

          {/* 快捷短语展开/收起 */}
          <Pressable
            onPress={() => setShowPhrases((v) => !v)}
            style={({ pressed }) => [
              styles.iconBtn,
              {
                backgroundColor: showPhrases ? c.primaryLight : 'transparent',
                opacity: pressed ? 0.6 : 1,
              },
            ]}
          >
            <MessageSquareText size={24} color={showPhrases ? c.primary : c.text} />
          </Pressable>

          {/* 客户订单面板 */}
          <Pressable
            onPress={() => setShowOrders(true)}
            style={({ pressed }) => [
              styles.iconBtn,
              { opacity: pressed ? 0.6 : 1 },
            ]}
          >
            <ShoppingBag size={24} color={c.text} />
          </Pressable>

        </View>
        <View style={[styles.inputBar, { backgroundColor: c.surface, borderTopColor: c.border }]}>
          <TextInput
            value={inputText}
            onChangeText={setInputText}
            placeholder="输入消息..."
            placeholderTextColor={c.textMuted}
            style={[styles.input, { color: c.text, backgroundColor: c.background }]}
            multiline
            maxLength={500}
            // 发送期间不禁用输入：editable=false 会收起键盘并中断连续输入
            // （用户常在等回执时接着打字），并发发送由发送按钮 disabled 与
            // handleSend 的 sending 判断拦截，不需要锁输入框
          />
          <Pressable
            onPress={handleSend}
            disabled={!inputText.trim() || sending}
            style={[styles.sendBtn, { backgroundColor: inputText.trim() && !sending ? c.primary : c.border }]}
          >
            {sending ? (
              <ActivityIndicator color="#FFF" />
            ) : (
              <Text style={styles.sendBtnText}>发送</Text>
            )}
          </Pressable>
        </View>
      </KeyboardAvoidingView>

      {/* 图片预览 */}
      <Modal visible={previewImage !== null} transparent onRequestClose={() => setPreviewImage(null)}>
        <View style={styles.previewOverlay}>
          <TouchableOpacity style={styles.previewClose} onPress={() => setPreviewImage(null)}>
            <Text style={styles.previewCloseText}>✕</Text>
          </TouchableOpacity>
          {previewImage && (
            <Image
              source={{ uri: previewImage }}
              style={styles.previewImage}
              resizeMode="contain"
            />
          )}
        </View>
      </Modal>

      {/* 客户订单面板 */}
      <Modal visible={showOrders} animationType="slide" onRequestClose={() => setShowOrders(false)}>
        <View style={[styles.ordersModal, { backgroundColor: c.background }]}>
          <View style={[styles.ordersHeader, { backgroundColor: c.surface, borderBottomColor: c.border }]}>
            <Text style={[styles.ordersTitle, { color: c.text }]}>客户订单</Text>
            <Pressable onPress={() => setShowOrders(false)} style={styles.ordersClose}>
              <X size={24} color={c.text} />
            </Pressable>
          </View>
          {account_id && buyer_id ? (
            <OrdersPanel accountId={account_id} buyerId={buyer_id} />
          ) : (
            <View style={styles.empty}><Text style={{ color: c.textMuted }}>无订单信息</Text></View>
          )}
        </View>
      </Modal>

      {/* 消息撤回操作菜单 */}
      <Modal
        visible={recallTarget !== null}
        transparent
        animationType="slide"
        onRequestClose={() => (recalling ? undefined : setRecallTarget(null))}
      >
        <Pressable style={styles.sheetOverlay} onPress={() => (recalling ? undefined : setRecallTarget(null))}>
          <Pressable style={[styles.sheet, { backgroundColor: c.surface }]} onPress={() => {}}>
            <View style={[styles.sheetHandle, { backgroundColor: c.border }]} />
            <Pressable
              style={[styles.sheetItem, styles.sheetItemBorder, { borderColor: c.border }]}
              onPress={handleRecall}
              disabled={recalling}
            >
              {recalling ? (
                <ActivityIndicator color={c.error} />
              ) : (
                <Text style={[styles.sheetItemText, { color: c.error }]}>撤回</Text>
              )}
            </Pressable>
            <Pressable
              style={styles.sheetItem}
              onPress={() => setRecallTarget(null)}
              disabled={recalling}
            >
              <Text style={[styles.sheetItemText, { color: c.text }]}>取消</Text>
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>

      {/* 快捷短语编辑/新建弹窗 */}
      <Modal
        visible={phraseModalVisible}
        transparent
        animationType="slide"
        onRequestClose={() => setPhraseModalVisible(false)}
      >
        <Pressable style={styles.sheetOverlay} onPress={() => setPhraseModalVisible(false)}>
          <Pressable
            style={[styles.sheet, styles.phraseEditorSheet, { backgroundColor: c.surface }]}
            onPress={() => {}}
          >
            <View style={styles.phraseEditorHeader}>
              <Text style={[styles.phraseEditorTitle, { color: c.text }]}>
                {editingPhrase ? '编辑短语' : '新建短语'}
              </Text>
              <Pressable onPress={() => setPhraseModalVisible(false)} disabled={savingPhrase}>
                <X size={20} color={c.text} />
              </Pressable>
            </View>

            <Text style={[styles.fieldLabel, { color: c.textSecondary }]}>标题</Text>
            <Input
              value={phraseTitle}
              onChangeText={setPhraseTitle}
              placeholder="短语标题（如：包邮）"
              maxLength={20}
              editable={!savingPhrase}
            />

            <Text style={[styles.fieldLabel, { color: c.textSecondary }]}>内容</Text>
            <Input
              value={phraseContent}
              onChangeText={setPhraseContent}
              placeholder="短语内容（如：亲，这款包邮哦~）"
              multiline
              maxLength={200}
              editable={!savingPhrase}
              style={styles.phraseContentInput}
            />

            <View style={styles.phraseEditorActions}>
              {editingPhrase && (
                <Pressable
                  style={[styles.editorDangerBtn, { borderColor: c.error }]}
                  onPress={() => {
                    const target = editingPhrase;
                    setPhraseModalVisible(false);
                    if (target) handleDeletePhrase(target);
                  }}
                  disabled={savingPhrase}
                >
                  <Trash2 size={16} color={c.error} />
                  <Text style={[styles.editorDangerText, { color: c.error }]}>删除</Text>
                </Pressable>
              )}
              <View style={{ flex: 1 }} />
              <Button
                label="取消"
                variant="ghost"
                onPress={() => setPhraseModalVisible(false)}
                disabled={savingPhrase}
              />
              <Button
                label={savingPhrase ? '保存中...' : '保存'}
                onPress={savePhrase}
                disabled={savingPhrase || !phraseTitle.trim() || !phraseContent.trim()}
              />
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  loadMoreBar: { paddingVertical: spacing.sm, alignItems: 'center' },
  chatHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderBottomWidth: 1 },
  chatHeaderMain: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginRight: spacing.sm },
  chatHeaderName: { ...typography.heading, flexShrink: 1 },
  accountTag: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radius.sm,
    borderWidth: 1,
    maxWidth: 130,
  },
  accountTagText: { ...typography.small },
  loadMoreText: { ...typography.caption },
  msgList: { padding: spacing.md, gap: spacing.sm },
  msgRow: { flexDirection: 'row', gap: spacing.sm, maxWidth: '100%' },
  msgRowSelf: { justifyContent: 'flex-end' },
  msgRowOther: { justifyContent: 'flex-start' },
  msgAvatar: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  msgAvatarText: { color: '#FFF', fontSize: 14, fontWeight: '600' },
  msgBubble: {
    maxWidth: '75%',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    borderWidth: 1,
  },
  msgText: { ...typography.body },
  msgImage: { width: 200, height: 200, borderRadius: radius.sm },
  videoPreview: { width: 180, height: 140, borderRadius: radius.sm, overflow: 'hidden', backgroundColor: '#1D2330', alignItems: 'center', justifyContent: 'center' },
  videoPlayBadge: { position: 'absolute', bottom: 8, flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: 'rgba(0,0,0,0.65)', padding: 6, borderRadius: radius.sm },
  videoCaption: { color: '#FFF', ...typography.caption },
  videoModal: { flex: 1, backgroundColor: '#000' },
  videoClose: { alignSelf: 'flex-end', padding: spacing.lg },
  videoWebView: { flex: 1, backgroundColor: '#000' },
  videoError: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.lg },
  msgSystem: { ...typography.caption, textAlign: 'center' },
  msgFailed: { ...typography.small, marginTop: spacing.xs },
  // 快捷短语面板
  phrasePanel: {
    paddingVertical: spacing.sm,
    borderTopWidth: 1,
  },
  // 横向列表必须给显式高度：默认 flexGrow:1 会撑满整屏；仅 flexGrow:0 时安卓初始测量会把文字压扁
  phraseScroll: { flexGrow: 0, minHeight: 64 },
  phraseList: { paddingHorizontal: spacing.md, gap: spacing.sm, alignItems: 'center' },
  phraseEmpty: { ...typography.body, textAlign: 'center', paddingVertical: spacing.md },
  phraseAddFirst: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    marginHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    borderWidth: 1,
    borderStyle: 'dashed',
  },
  phraseAddFirstText: { ...typography.body, fontWeight: '600' },
  phraseChip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.lg,
    borderWidth: 1,
    minWidth: 88,
    maxWidth: 160,
  },
  phraseChipTitle: { ...typography.caption, fontWeight: '600', marginBottom: 2 },
  phraseChipContent: { ...typography.small },
  phraseAddChip: {
    width: 40,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.lg,
    borderWidth: 1,
    borderStyle: 'dashed',
  },
  // 输入栏
  actionBar: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, paddingHorizontal: spacing.md, paddingVertical: spacing.xs, borderTopWidth: 1 },
  inputBar: {
    flexDirection: 'row',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: spacing.sm,
    borderTopWidth: 1,
    alignItems: 'flex-end',
  },
  iconBtn: {
    width: 36,
    height: 36,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.md,
  },
  input: {
    ...typography.body,
    flex: 1,
    minHeight: 36,
    maxHeight: 100,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  sendBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    minHeight: 36,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendBtnText: { color: '#FFF', fontWeight: '600' },
  empty: { alignItems: 'center', justifyContent: 'center', paddingVertical: 60 },
  emptyText: { ...typography.body },
  // 图片预览
  previewOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.9)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  previewClose: { position: 'absolute', top: 50, right: 20, zIndex: 1 },
  previewCloseText: { color: '#FFF', fontSize: 28 },
  previewImage: { width: '90%', height: '70%' },
  // 操作菜单（底部弹窗）
  sheetOverlay: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(0,0,0,0.4)',
  },
  sheet: {
    borderTopLeftRadius: radius.xl,
    borderTopRightRadius: radius.xl,
    paddingBottom: spacing.xl,
  },
  sheetHandle: {
    width: 36,
    height: 4,
    borderRadius: 2,
    alignSelf: 'center',
    marginTop: spacing.sm,
    marginBottom: spacing.xs,
  },
  sheetItem: {
    paddingVertical: spacing.lg,
    alignItems: 'center',
  },
  sheetItemBorder: {
    borderTopWidth: 0,
    borderBottomWidth: 1,
  },
  sheetItemText: { ...typography.body, fontWeight: '600' },
  // 快捷短语编辑弹窗
  phraseEditorSheet: {
    padding: spacing.lg,
    maxHeight: '80%',
  },
  phraseEditorHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
  },
  phraseEditorTitle: { ...typography.heading },
  fieldLabel: {
    ...typography.small,
    marginTop: spacing.sm,
    marginBottom: spacing.xs,
  },
  phraseContentInput: {
    minHeight: 72,
    maxHeight: 120,
    textAlignVertical: 'top',
  },
  phraseEditorActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: spacing.lg,
  },
  editorDangerBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    borderWidth: 1,
  },
  editorDangerText: { ...typography.body, fontWeight: '600' },
  ordersModal: { flex: 1, marginTop: 50 },
  ordersHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1 },
  ordersTitle: { ...typography.title },
  ordersClose: { padding: spacing.sm },
});
