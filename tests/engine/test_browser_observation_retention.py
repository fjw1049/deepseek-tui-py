import json

from deepseek_tui.engine.context import prune_superseded_browser_observations
from deepseek_tui.protocol.messages import Message, ToolUseBlock


def exchange(i, text, *, tool='browser_use', offset=0):
    payload = {'success': True, 'receipt': {'evidence_ref': f'tool:{i}', 'effect': 'confirmed'},
               'observation': {'document_id': 'doc', 'tab_id': 'tab', 'url': 'https://test/',
                               'observation_id': str(i), 'text_offset': offset, 'text': text,
                               'elements': [{'name': 'Target ' * 1000}] * 5}}
    return [Message.assistant_with_tools([ToolUseBlock(id=str(i), name=tool, input={})]),
            Message.tool_result(str(i), json.dumps(payload) + '\nReminder retained')]


def test_single_turn_reclaims_old_targets_but_keeps_unique_text_and_receipts():
    messages = [Message.user('Long browser task')]
    for i in range(7):
        messages.extend(exchange(i, 'unique first result' if i == 0 else 'Repeated page'))
    assert prune_superseded_browser_observations(messages) == 4
    old = messages[2].content[0].content
    assert 'unique first result' in old and 'tool:0' in old
    assert 'targets_archived' in old and 'Reminder retained' in old
    assert 'elements' not in old
    assert 'Repeated text retained' in messages[4].content[0].content
    assert 'elements' in messages[-1].content[0].content


def test_pagination_and_nonbrowser_outputs_are_not_replaced():
    messages = [Message.user('Read all pages')]
    for i in range(8):
        messages.extend(exchange(i, 'Page data', offset=i * 100))
    messages.extend(exchange(99, 'File content', tool='read_file'))
    original = [m.model_dump() for m in messages]
    assert prune_superseded_browser_observations(messages) == 0
    assert [m.model_dump() for m in messages] == original
