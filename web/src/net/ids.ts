/** Client msg_id: `m_` + a v4 UUID without dashes (34 chars, within 8..64 of [A-Za-z0-9_-]). */
export function newMsgId(): string {
  return `m_${crypto.randomUUID().replace(/-/g, "")}`;
}
