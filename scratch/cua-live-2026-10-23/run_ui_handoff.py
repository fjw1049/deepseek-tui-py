import asyncio,json
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parent
async def main():
 token=(Path.home()/'.deepseek/runtime.token').read_text().strip()
 async with httpx.AsyncClient(base_url='http://127.0.0.1:7878',headers={'Authorization':'Bearer '+token},timeout=30) as c:
  r=await c.post('/v1/threads',json={'title':'CUA前端授权与接管验收','workspace':str(ROOT/'desktop-fixture'),'provider':'endpoint','model':'qwen-3-8-max'})
  r.raise_for_status(); tid=r.json()['id']; (ROOT/'ui-thread.json').write_text(json.dumps({'thread_id':tid}))
  prompt=('这是已授权的真实桌面交接验收。只操作 TextEdit（com.apple.TextEdit）与已打开的测试文件 '+str(ROOT/'desktop-fixture/note.txt')+'，不要写入任何内容。先用 cua_js 获取 TextEdit 并观察该文件。随后必须调用 request_user_input，kind=action，surface=desktop，reason=请人工点击 TextEdit 的 note.txt 标题栏后选择已完成，以验证交接。等待后重新初始化句柄，观察并核对文件没有变化，然后汇报。禁止用 shell 替代桌面操作，不要申请永久权限。')
  r=await c.post(f'/v1/threads/{tid}/turns',json={'prompt':prompt,'provider':'endpoint','model':'qwen-3-8-max'});r.raise_for_status()
  print(json.dumps({'thread_id':tid,'turn_id':r.json()['turn']['id']}),flush=True)
  with (ROOT/'ui-events.jsonl').open('a') as out:
   async with c.stream('GET',f'/v1/threads/{tid}/events',params={'since_seq':0},timeout=None) as stream:
    async for line in stream.aiter_lines():
     if not line.startswith('data:'):continue
     event=json.loads(line[5:]);out.write(json.dumps(event,ensure_ascii=False)+'\n');out.flush()
     name=event.get('event','')
     if name in {'turn.completed','turn.failed','turn.interrupted'}:
      print(json.dumps(event,ensure_ascii=False)[:1800],flush=True);break
     if 'input' in name or 'approval' in name or 'tool' in name:
      print(json.dumps(event,ensure_ascii=False)[:1800],flush=True)
asyncio.run(main())
