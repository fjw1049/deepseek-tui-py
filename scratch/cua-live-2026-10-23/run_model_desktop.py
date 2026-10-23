import asyncio,json
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parent
async def main():
 token=(Path.home()/'.deepseek/runtime.token').read_text().strip()
 async with httpx.AsyncClient(base_url='http://127.0.0.1:7878',headers={'Authorization':'Bearer '+token},timeout=30) as c:
  r=await c.post('/v1/threads',json={'title':'CUA真实验收-临时文档','workspace':str(ROOT/'desktop-fixture'),'provider':'endpoint','model':'qwen-3-8-max'})
  r.raise_for_status(); tid=r.json()['id']; (ROOT/'model-thread.json').write_text(json.dumps({'thread_id':tid}))
  prompt=('这是已授权的本机电脑控制验收。只操作 TextEdit（com.apple.TextEdit）和指定测试文件：'+str(ROOT/'desktop-fixture/note.txt')+'。请使用 cua_js 通过 TextEdit 打开此文件，在末尾追加一行“真实桌面验收：中文输入与保存成功。”并保存。禁止用 shell、Python、AppleScript 或文件写入工具代替界面输入。保存后可以用 read_file 只读核对文件。然后用 request_user_input 普通提问询问“是否继续交接验收？”并等待回答。不要操作其他文件或应用，不要申请长期权限。')
  r=await c.post(f'/v1/threads/{tid}/turns',json={'prompt':prompt,'provider':'endpoint','model':'qwen-3-8-max'});r.raise_for_status()
  print(json.dumps({'thread_id':tid,'turn_id':r.json()['turn']['id']}),flush=True)
  with (ROOT/'model-events.jsonl').open('a') as out:
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
