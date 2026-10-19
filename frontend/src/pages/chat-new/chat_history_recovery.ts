import type { ChatMessage, Conversation } from '@/api/chatNew'
import { mergeConversations, mergeMessages } from './chat_history_merge'

export interface MessageCache { msgs: ChatMessage[]; hasMore: boolean; cursor: number | null }
export interface ConversationCache { convs: Conversation[]; hasMore: boolean; cursor: number | null }
export interface RecoveryBoundary<T> { cache: T; nextCursor: number | null }

/** Live pushes and repeated disconnects must not move an unfinished recovery boundary. */
export class ChatHistoryRecovery {
  readonly messages = new Map<string, Map<string, RecoveryBoundary<MessageCache>>>()
  readonly conversations = new Map<string, RecoveryBoundary<ConversationCache>>()
  private readonly generations = new Map<string, number>()

  generation(accountId: string) { return this.generations.get(accountId) ?? 0 }
  message(accountId: string, cid: string) { return this.messages.get(accountId)?.get(cid) }

  ensureMessage(accountId: string, cid: string, cache: MessageCache) {
    let account = this.messages.get(accountId)
    if (!account) { account = new Map(); this.messages.set(accountId, account) }
    if (!account.has(cid)) account.set(cid, { cache: { ...cache, msgs: [...cache.msgs] }, nextCursor: null })
    return account.get(cid)!
  }

  ensureConversations(accountId: string, cache: ConversationCache) {
    if (!this.conversations.has(accountId)) {
      this.conversations.set(accountId, { cache: { ...cache, convs: [...cache.convs] }, nextCursor: null })
    }
    return this.conversations.get(accountId)!
  }

  prepare(accountId: string, conversations: ConversationCache | undefined,
    messages: Record<string, MessageCache>, disconnected = false) {
    if (disconnected) {
      this.generations.set(accountId, this.generation(accountId) + 1)
      const pending = this.conversations.get(accountId)
      if (pending) pending.nextCursor = null
      this.messages.get(accountId)?.forEach((boundary) => { boundary.nextCursor = null })
    }
    if (conversations) this.ensureConversations(accountId, conversations)
    for (const [cid, cache] of Object.entries(messages)) this.ensureMessage(accountId, cid, cache)
  }
}

const MAX_RECOVERY_PAGES = 20

interface RecoveryPage<T> { items: T[]; hasMore: boolean; nextCursor: number | null }
interface RecoveryResult<T> { items: T[]; hasMore: boolean; cursor: number | null; complete: boolean }
function assertCursor<T>(page: RecoveryPage<T>, cursor: number | null) {
  if (page.hasMore && (page.nextCursor === null || !Number.isFinite(page.nextCursor) ||
    (cursor !== null && page.nextCursor >= cursor))) {
    throw new Error('聊天分页游标异常，请重试补偿')
  }
}

/** Fetch newest pages until a message already present before the disconnect is found. */
export async function recoverMessages(
  fetchPage: (cursor: number | undefined, limit: number) => Promise<RecoveryPage<ChatMessage>>,
  boundary: RecoveryBoundary<MessageCache>,
  isCurrent: () => boolean,
): Promise<RecoveryResult<ChatMessage> | null> {
  const knownIds = new Set(boundary.cache.msgs.map((message) => message.messageId).filter(Boolean))
  let cursor = boundary.nextCursor
  let items: ChatMessage[] = []
  for (let page = 0; page < MAX_RECOVERY_PAGES; page += 1) {
    if (!isCurrent()) return null
    const result = await fetchPage(cursor ?? undefined, 100)
    if (!isCurrent()) return null
    assertCursor(result, cursor)
    items = mergeMessages(items, result.items, 'append')
    const reachedKnown = result.items.some((message) => message.messageId && knownIds.has(message.messageId))
    if (!result.hasMore || reachedKnown || boundary.cache.msgs.length === 0) {
      return { items, hasMore: reachedKnown && result.hasMore ? boundary.cache.hasMore : result.hasMore,
        cursor: reachedKnown && result.hasMore ? boundary.cache.cursor : result.nextCursor, complete: true }
    }
    assertCursor(result, cursor)
    cursor = result.nextCursor
  }
  return { items, hasMore: true, cursor, complete: false }
}

/** Fetch conversation pages through the cursor already loaded before disconnect. */
export async function recoverConversations(
  fetchPage: (cursor: number | undefined) => Promise<RecoveryPage<Conversation>>,
  boundary: RecoveryBoundary<ConversationCache>,
  isCurrent: () => boolean,
): Promise<RecoveryResult<Conversation> | null> {
  let cursor = boundary.nextCursor
  let items: Conversation[] = []
  for (let page = 0; page < MAX_RECOVERY_PAGES; page += 1) {
    if (!isCurrent()) return null
    const result = await fetchPage(cursor ?? undefined)
    if (!isCurrent()) return null
    assertCursor(result, cursor)
    items = mergeConversations(items, result.items)
    const reachedOldRange = boundary.cache.cursor !== null && result.nextCursor !== null &&
      result.nextCursor <= boundary.cache.cursor
    if (!result.hasMore || reachedOldRange || boundary.cache.convs.length === 0) {
      return { items, hasMore: reachedOldRange && result.hasMore ? boundary.cache.hasMore : result.hasMore,
        cursor: reachedOldRange && result.hasMore ? boundary.cache.cursor : result.nextCursor, complete: true }
    }
    assertCursor(result, cursor)
    cursor = result.nextCursor
  }
  return { items, hasMore: true, cursor, complete: false }
}
