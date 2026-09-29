import type { ChatMessage } from '@/api/wrappers/chat';
import { logger } from '@/lib/logger';
import { AppState, type AppStateStatus } from 'react-native';

const HEARTBEAT_INTERVAL = 20000;
const RECONNECT_BASE_DELAY = 3000;
const RECONNECT_MAX_DELAY = 30000;
const RECONNECT_MAX_RETRIES = 10;

type MessageListener = (accountId: string, cid: string, message: ChatMessage) => void;
type StatusListener = (accountId: string, connected: boolean) => void;
type ReconnectedListener = (accountId: string) => void;

interface WsConnection {
  ws: WebSocket;
  heartbeatTimer: ReturnType<typeof setInterval> | null;
  reconnectTimer: ReturnType<typeof setTimeout> | null;
  closed: boolean;
  retryCount: number;
}

class WsManager {
  private connections = new Map<string, WsConnection>();
  private messageListeners = new Set<MessageListener>();
  private statusListeners = new Set<StatusListener>();
  private reconnectedListeners = new Set<ReconnectedListener>();
  private serverUrl: string | null = null;
  private token: string | null = null;
  private activeCid: string | null = null;
  private appStateSub: { remove: () => void } | null = null;
  /**
   * 曾经建连成功的账号集合
   *
   * 用于区分首次建连与断线重连：断连期间的推送已永久丢失，
   * 只有重连才需要通知调用方补偿拉取；首次建连由页面初始加载负责。
   */
  private everConnected = new Set<string>();

  constructor() {
    // 前台恢复时重连所有掉线的账号（重试耗尽后 WS 不会自行恢复）
    this.appStateSub = AppState.addEventListener(
      'change',
      this.handleAppStateChange,
    );
  }

  private handleAppStateChange = (state: AppStateStatus) => {
    if (state !== 'active') return;
    for (const [accountId, conn] of this.connections) {
      const readyState = conn.ws.readyState;
      const dead =
        conn.closed === false &&
        (readyState === WebSocket.CLOSED || readyState === WebSocket.CLOSING);
      const stuckConnecting =
        conn.closed === false &&
        readyState === WebSocket.CONNECTING &&
        conn.retryCount > 0;
      if (dead || stuckConnecting) {
        logger.info('WS', `前台恢复，重连: accountId=${accountId}`);
        this.connections.delete(accountId);
        this.connect(accountId, 0);
      }
    }
  };

  configure(serverUrl: string, token: string) {
    this.serverUrl = serverUrl;
    this.token = token;
  }

  setActiveCid(cid: string | null) {
    this.activeCid = cid;
  }

  getActiveCid() {
    return this.activeCid;
  }

  onMessage(listener: MessageListener): () => void {
    this.messageListeners.add(listener);
    return () => this.messageListeners.delete(listener);
  }

  onStatusChange(listener: StatusListener): () => void {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  }

  /**
   * 订阅重连成功事件（首次建连不触发）
   *
   * 断连期间的推送会永久丢失，调用方应借此重新拉取会话与消息补齐缺口。
   */
  onReconnected(listener: ReconnectedListener): () => void {
    this.reconnectedListeners.add(listener);
    return () => this.reconnectedListeners.delete(listener);
  }

  connect(accountId: string, initialRetryCount = 0) {
    if (!this.serverUrl || !this.token) return;
    // 已有连接且未关闭则跳过
    const existing = this.connections.get(accountId);
    if (existing && !existing.closed) return;
    // 清理可能残留的旧连接
    if (existing) this.connections.delete(accountId);

    const wsUrl = this.buildWsUrl(accountId);
    if (!wsUrl) {
      logger.warn('WS', `无法构建 WS URL (serverUrl或token未配置), accountId=${accountId}`);
      return;
    }

    logger.info('WS', `连接中: ${wsUrl.replace(/token=[^&]+/, 'token=***')}`);
    const connection: WsConnection = {
      ws: new WebSocket(wsUrl),
      heartbeatTimer: null,
      reconnectTimer: null,
      closed: false,
      retryCount: initialRetryCount,
    };

    connection.ws.onopen = () => {
      // 连接成功，重置重试计数
      connection.retryCount = 0;
      logger.info('WS', `已连接: accountId=${accountId}`);
      this.notifyStatus(accountId, true);
      // 重连：断连期间的推送已丢失，通知调用方补偿拉取
      const isReconnect = this.everConnected.has(accountId);
      this.everConnected.add(accountId);
      if (isReconnect) this.notifyReconnected(accountId);
      connection.heartbeatTimer = setInterval(() => {
        if (connection.ws.readyState === WebSocket.OPEN) {
          connection.ws.send(JSON.stringify({ type: 'ping' }));
        }
      }, HEARTBEAT_INTERVAL);
    };

    connection.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'new_message' && data.cid && data.message) {
          logger.debug('WS', `新消息: accountId=${accountId} cid=${data.cid}`);
          this.messageListeners.forEach((fn) =>
            fn(accountId, data.cid, data.message as ChatMessage),
          );
        }
      } catch (e) {
        logger.warn('WS', `消息解析失败: ${(e as Error).message}`);
      }
    };

    connection.ws.onclose = (event) => {
      logger.warn('WS', `连接关闭: accountId=${accountId} code=${event.code} reason=${event.reason || '无'}`);
      if (connection.heartbeatTimer) {
        clearInterval(connection.heartbeatTimer);
        connection.heartbeatTimer = null;
      }
      this.notifyStatus(accountId, false);

      if (connection.closed) return;
      if (event.code === 4401 || event.code === 4403) {
        logger.warn('WS', `认证失败(${event.code})，不再重连: accountId=${accountId}`);
        // 认证失败后重新登录再建连应按首次连接处理，避免触发一次无意义的补拉
        this.everConnected.delete(accountId);
        return;
      }

      // 指数退避：delay = base * 2^retry，上限 maxDelay
      const delay = Math.min(
        RECONNECT_BASE_DELAY * Math.pow(2, connection.retryCount),
        RECONNECT_MAX_DELAY,
      );
      connection.retryCount++;

      if (connection.retryCount > RECONNECT_MAX_RETRIES) {
        logger.error('WS', `达到最大重试次数(${RECONNECT_MAX_RETRIES})，停止重连: accountId=${accountId}`);
        return;
      }

      logger.info('WS', `${delay}ms 后重连 (第${connection.retryCount}次): accountId=${accountId}`);
      const nextRetryCount = connection.retryCount;
      connection.reconnectTimer = setTimeout(() => {
        this.connections.delete(accountId);
        this.connect(accountId, nextRetryCount);
      }, delay);
    };

    connection.ws.onerror = () => {
      // onclose will handle reconnection
    };

    this.connections.set(accountId, connection);
  }

  disconnect(accountId: string) {
    const conn = this.connections.get(accountId);
    if (!conn) return;
    conn.closed = true;
    if (conn.heartbeatTimer) clearInterval(conn.heartbeatTimer);
    if (conn.reconnectTimer) clearTimeout(conn.reconnectTimer);
    conn.ws.close();
    this.connections.delete(accountId);
    // 主动断开（切账号/离开页面）清除“曾连接”标记，下次建连按首次处理。
    // 网络掉线走内部重试路径，不经过这里，标记得以保留并触发补拉。
    this.everConnected.delete(accountId);
    this.notifyStatus(accountId, false);
  }

  disconnectAll() {
    for (const id of this.connections.keys()) {
      this.disconnect(id);
    }
  }

  isConnected(accountId: string): boolean {
    const conn = this.connections.get(accountId);
    return conn?.ws.readyState === WebSocket.OPEN;
  }

  private buildWsUrl(accountId: string): string | null {
    if (!this.serverUrl || !this.token) return null;
    let url = this.serverUrl;
    if (url.startsWith('https://')) {
      url = `wss://${url.slice(8)}`;
    } else if (url.startsWith('http://')) {
      url = `ws://${url.slice(7)}`;
    } else if (!url.startsWith('ws://') && !url.startsWith('wss://')) {
      url = `ws://${url}`;
    }
    return `${url}/api/v1/chat-new/ws/${accountId}?token=${encodeURIComponent(this.token)}`;
  }

  private notifyStatus(accountId: string, connected: boolean) {
    this.statusListeners.forEach((fn) => fn(accountId, connected));
  }

  private notifyReconnected(accountId: string) {
    this.reconnectedListeners.forEach((fn) => fn(accountId));
  }
}

export const wsManager = new WsManager();
