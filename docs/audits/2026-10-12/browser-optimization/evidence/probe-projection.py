import json
from pathlib import Path
from deepseek_tui.browser.context import project_result
from deepseek_tui.engine.context import compact_tool_result_for_context
from deepseek_tui.tools.registry import ToolResult

root = Path('/private/tmp/browser-optimization-20261012/observe')
cases = {
    'status_without_observation': {
        'success': True,
        'content': {'active': True, 'generation': 3, 'log': [
            {'action': 'click', 'action_id': str(i), 'receipt': 'x' * 250}
            for i in range(80)]},
        'artifact': None,
    },
    'schema_valid_deep_shadow_scope': {
        'success': True,
        'observation': {'observation_id': 'obs-current', 'text': 'Page',
            'scope_shadow_path': ['#' + 'a' * 999 for _ in range(16)],
            'elements': [{'ref': 'e0', 'role': 'button', 'name': 'Go'}]},
    },
}
results=[]
for name, value in cases.items():
    output=compact_tool_result_for_context('gpt-4o', 'browser_use',
        ToolResult(True, json.dumps(value), metadata={'browser':value}), pressure_ratio=0.6)
    data=json.loads(output)
    results.append({'case':name, 'evidence_level':'synthetic-current-implementation',
        'budget_chars':6000, 'output_chars':len(output), 'valid_json':True,
        'exceeds_budget':len(output)>6000,
        'observation_id':data.get('observation',{}).get('observation_id')})
(root/'projection-result.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results))
