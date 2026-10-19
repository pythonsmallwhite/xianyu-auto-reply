/** Chat history merge helpers shared by live pushes, refreshes and recovery. */
import type { ChatMessage, Conversation } from '@/api/chatNew'

export const toTimestampMs = (timestamp: number) =>
  timestamp < 1_000_000_000_000 ? timestamp * 1000 : timestamp

const sameUnidentifiedMessage = (left: ChatMessage, right: ChatMessage) =>
  !left.messageId && !right.messageId && left.isSelf === right.isSelf &&
  left.type === right.type && left.text === right.text &&
  (left.type !== 'video' || left.videoUrl === right.videoUrl) &&
  Math.abs(toTimestampMs(left.time) - toTimestampMs(right.time)) < 5000

/** Keep stable-ID messages distinct; only local, unidentified placeholders use a narrow fallback. */
export function mergeMessages(
  existing: ChatMessage[],
  incoming: ChatMessage[],
  mode: 'append' | 'prepend' | 'replace' = 'append',
): ChatMessage[] {
  const seenIds = new Set(existing.map((message) => message.messageId).filter(Boolean))
  const accepted: ChatMessage[] = []
  for (const message of incoming) {
    if (message.messageId) {
      if (seenIds.has(message.messageId)) continue
      seenIds.add(message.messageId)
    } else if (existing.some((item) => sameUnidentifiedMessage(message, item)) ||
      accepted.some((item) => sameUnidentifiedMessage(message, item))) {
      continue
    }
    accepted.push(message)
  }
  const merged = mode === 'prepend' ? [...accepted, ...existing] : [...existing, ...accepted]
  return merged.sort((left, right) => toTimestampMs(left.time) - toTimestampMs(right.time))
}

export const appendMsg = (messages: ChatMessage[], message: ChatMessage) =>
  mergeMessages(messages, [message], 'append')

/** Preserve live updates received while a conversation HTTP snapshot was in flight. */
export function mergeConversations(existing: Conversation[], incoming: Conversation[]): Conversation[] {
  const previous = new Map(existing.map((conversation) => [conversation.cid, conversation]))
  const merged = new Map<string, Conversation>()
  for (const conversation of incoming) {
    const local = previous.get(conversation.cid)
    merged.set(conversation.cid, local &&
      toTimestampMs(local.lastMessageTime) > toTimestampMs(conversation.lastMessageTime)
      ? { ...conversation, lastMessageTime: local.lastMessageTime,
        lastMessageSummary: local.lastMessageSummary, unreadCount: local.unreadCount }
      : conversation)
  }
  for (const conversation of existing) {
    if (!merged.has(conversation.cid)) merged.set(conversation.cid, conversation)
  }
  return [...merged.values()].sort((left, right) =>
    toTimestampMs(right.lastMessageTime) - toTimestampMs(left.lastMessageTime))
}
