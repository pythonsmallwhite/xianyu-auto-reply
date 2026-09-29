/**
 * 在线聊天 WebSocket Hook
 *
 * 管理与后端的多账号 WebSocket 连接，接收 IM 实时推送消息并更新到前端状态。
 * 每个已连接账号维护一条独立的 WebSocket，支持自动重连和心跳保活。
 */
import { useEffect, useRef, useCallback } from 'react'
import { createChatNewWebSocket, type WsPushMessage, type ChatMessage } from '@/api/chatNew'

/** 心跳间隔（毫秒） */
const HEARTBEAT_INTERVAL = 20000
/** 重连延迟（毫秒） */
const RECONNECT_DELAY = 3000

/** 单个账号的 WebSocket 连接状态 */
interface WsConnection {
  ws: WebSocket
  heartbeat: ReturnType<typeof setInterval> | null
  reconnect: ReturnType<typeof setTimeout> | null
  closed: boolean
}

interface UseChatNewWsOptions {
  /** 所有已连接的账号ID列表，每个都会建立独立的 WebSocket 连接 */
  accountIds: string[]
  /** 收到新消息时的回调（包含来源账号ID） */
  onNewMessage: (accountId: string, cid: string, msg: ChatMessage) => void
  /** WebSocket 断连时的回调 */
  onDisconnect?: (accountId: string) => void
  /**
   * 重连成功时的回调（首次建连不触发）
   *
   * 断线期间的推送会永久丢失，调用方必须借此重新拉取会话与消息补齐缺口。
   */
  onReconnected?: (accountId: string) => void
}

/**
 * 在线聊天(新) 多账号 WebSocket 连接 Hook
 *
 * 根据 accountIds 列表自动管理每个账号的 WebSocket 连接。
 * 新增账号自动建连，移除的账号自动断开，已有账号保持不变。
 */
export function useChatNewWs({ accountIds, onNewMessage, onDisconnect, onReconnected }: UseChatNewWsOptions) {
  const connectionsRef = useRef<Map<string, WsConnection>>(new Map())
  const onNewMessageRef = useRef(onNewMessage)
  const onDisconnectRef = useRef(onDisconnect)
  const onReconnectedRef = useRef(onReconnected)
  /**
   * 曾经建连成功的账号集合
   *
   * 用于区分“首次连接”和“断线重连”：只有断线重连才需要补偿拉取，
   * 首次连接由页面自身的初始加载负责，重复拉取会造成请求浪费。
   * 账号被主动移除（或组件卸载）时会一并清理，保证下次添加仍算首次连接。
   */
  const everConnectedRef = useRef<Set<string>>(new Set())

  // 保持回调引用最新
  useEffect(() => { onNewMessageRef.current = onNewMessage }, [onNewMessage])
  useEffect(() => { onDisconnectRef.current = onDisconnect }, [onDisconnect])
  useEffect(() => { onReconnectedRef.current = onReconnected }, [onReconnected])

  /** 清理单个账号的连接（仅关闭底层连接，保留“曾连接”标记） */
  const disposeConnection = useCallback((aid: string) => {
    const conn = connectionsRef.current.get(aid)
    if (!conn) return
    conn.closed = true
    if (conn.heartbeat) clearInterval(conn.heartbeat)
    if (conn.reconnect) clearTimeout(conn.reconnect)
    conn.ws.onopen = null
    conn.ws.onmessage = null
    conn.ws.onerror = null
    conn.ws.onclose = null
    if (conn.ws.readyState === WebSocket.OPEN || conn.ws.readyState === WebSocket.CONNECTING) {
      conn.ws.close()
    }
    connectionsRef.current.delete(aid)
  }, [])

  /**
   * 彻底移除账号连接
   *
   * 与 disposeConnection 的区别在于会清除“曾连接”标记，
   * 使该账号下次被添加时重新按首次连接处理。
   */
  const cleanupAccount = useCallback((aid: string) => {
    disposeConnection(aid)
    everConnectedRef.current.delete(aid)
  }, [disposeConnection])

  /** 为指定账号建立 WebSocket 连接 */
  const connectAccount = useCallback((aid: string) => {
    disposeConnection(aid)

    const ws = createChatNewWebSocket(aid)
    const conn: WsConnection = { ws, heartbeat: null, reconnect: null, closed: false }
    connectionsRef.current.set(aid, conn)

    ws.onopen = () => {
      conn.heartbeat = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, HEARTBEAT_INTERVAL)
      // 断线重连：断连期间推送已丢失，通知调用方补偿拉取
      const isReconnect = everConnectedRef.current.has(aid)
      everConnectedRef.current.add(aid)
      if (isReconnect) onReconnectedRef.current?.(aid)
    }

    ws.onmessage = (event) => {
      try {
        const data: WsPushMessage = JSON.parse(event.data)
        if (data.event === 'new_message' && data.cid && data.message) {
          onNewMessageRef.current(aid, data.cid, data.message)
        }
      } catch {
        // 解析失败，忽略
      }
    }

    ws.onerror = () => {}

    ws.onclose = (event) => {
      if (conn.heartbeat) {
        clearInterval(conn.heartbeat)
        conn.heartbeat = null
      }
      if (!conn.closed && onDisconnectRef.current) {
        onDisconnectRef.current(aid)
      }
      // 鉴权失败（4401 未认证 / 4403 无权限）为终止性关闭，不再重连，避免请求风暴
      const isAuthFailure = event.code === 4401 || event.code === 4403
      if (isAuthFailure) {
        conn.closed = true
        connectionsRef.current.delete(aid)
        everConnectedRef.current.delete(aid)
        return
      }
      // 其他原因断开则自动重连（除非主动关闭）
      if (!conn.closed) {
        conn.reconnect = setTimeout(() => {
          if (!conn.closed) connectAccount(aid)
        }, RECONNECT_DELAY)
      }
    }
  }, [disposeConnection])

  // 根据 accountIds 变化增量管理连接（只增减差异，不断开已有连接）
  const accountIdsKey = accountIds.join(',')
  useEffect(() => {
    const currentIds = new Set(accountIds)
    const existingIds = new Set(connectionsRef.current.keys())

    // 新增的账号 → 建连
    for (const aid of currentIds) {
      if (!existingIds.has(aid)) {
        connectAccount(aid)
      }
    }
    // 移除的账号 → 断开
    for (const aid of existingIds) {
      if (!currentIds.has(aid)) {
        cleanupAccount(aid)
      }
    }
  }, [accountIdsKey]) // eslint-disable-line react-hooks/exhaustive-deps

  // 组件卸载时清理所有连接
  useEffect(() => {
    return () => {
      for (const aid of Array.from(connectionsRef.current.keys())) {
        cleanupAccount(aid)
      }
    }
  }, [cleanupAccount])
}
