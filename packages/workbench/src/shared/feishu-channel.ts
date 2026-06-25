/**
 * Feishu/Lark helpers shared by UI and tests.
 * Mirrors Python ``feishu_receive_id_type`` in ``automation/inbox.py``.
 */

export function feishuReceiveIdType(receiveId: string): 'chat_id' | 'open_id' | 'union_id' {
  const rid = receiveId.trim()
  if (rid.startsWith('oc_')) return 'chat_id'
  if (rid.startsWith('ou_')) return 'open_id'
  if (rid.startsWith('on_')) return 'union_id'
  return 'open_id'
}
