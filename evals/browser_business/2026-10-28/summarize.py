"""Derive metrics from completed raw runs; never count diagnostics as results."""
import gzip
import ast
import re
import json
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent

def rows():
    output=[]
    for path in sorted([*HERE.glob('*-*-*.json'), *HERE.glob('*-*-*.json.gz')]):
        if not path.name.startswith(('before-','after-')):
            continue
        data=json.loads(gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes())
        events=data.get('events',[])
        calls=[e['data']['tool_call'] for e in events if e['type']=='ToolCallEvent']
        calls=[({'name':re.search(r" name='([^']+)'",c)[1],
                 'arguments':ast.literal_eval(c.split(' arguments=',1)[1])}
                if isinstance(c,str) else c) for c in calls]
        results=[e['data'] for e in events if e['type']=='ToolResultEvent']
        failures=[r for r in results if not r['success']]
        output.append(dict(file=path.name,version=data['version'],case=data['case'],repeat=data['repeat'],
            complete='pass' in data,passed=data.get('pass'),seconds=data.get('seconds'),
            requests=len(data.get('requests',[])),tool_calls=len(calls),failed_calls=len(failures),
            actions=dict(Counter(c['arguments'].get('action',c['name']) for c in calls)),
            max_message_chars=max((r['message_chars'] for r in data.get('requests',[])),default=0),
            input_tokens=sum((r.get('usage') or {}).get('input_tokens',0) for r in data.get('requests',[])),
            cache_read_tokens=sum((r.get('usage') or {}).get('cache_read_input_tokens',0) for r in data.get('requests',[])),
            human_requests=sum(t.get('error')=='Human input required' for t in data.get('turns',[])),
            false_completed=sum((t.get('outcome') or {}).get('status')=='completed' and not t['verdict']['pass'] for t in data.get('turns',[])),
            turns=[{'passed':t['verdict']['pass'],'checks':t['verdict'].get('checks'),
                    'error':t.get('error')} for t in data.get('turns',[])],
            errors=[{'tool':r['tool_name'],'content':r['content'][:500]} for r in failures],
            error=data.get('error')))
    return output

if __name__=='__main__':
    data=rows()
    (HERE/'metrics.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
    for r in data:
        print(r['version'],r['case'],r['repeat'],r['complete'],r['passed'],r['requests'],r['failed_calls'],r['seconds'])
