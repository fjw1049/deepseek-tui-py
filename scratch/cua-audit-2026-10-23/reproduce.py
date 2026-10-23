import asyncio, base64, io, random, tempfile, shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from PIL import Image
from deepseek_tui import media
from deepseek_tui.cua.engine import CuaEngineMixin
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.browser.service import BrowserService
from deepseek_tui.cua.session import CuaSession, DesktopLease
from deepseek_tui.cua.tools import CuaTool
from deepseek_tui.config.models import CuaConfig
from deepseek_tui.tools.task_delivery import TaskDelivery, FinishTaskTool
from deepseek_tui.tools.registry import ToolContext, ToolError

async def main():
    events = []
    async def emit(event): events.append(type(event).__name__)
    fake = SimpleNamespace(handle=SimpleNamespace(pending_user_inputs={}, cancel_event=asyncio.Event(), emit=emit))
    task = asyncio.create_task(Engine._await_user_input_raw(fake, 'permission', [], purpose='cua_permission'))
    await asyncio.sleep(0)
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass
    print('cancelled_permission_events=', events, 'pending=', fake.handle.pending_user_inputs)

    session = SimpleNamespace(end_turn=AsyncMock(), close=AsyncMock(), reset_reason='')
    fake = SimpleNamespace(_cua_session=session)
    await CuaEngineMixin._release_cua(fake)
    print('ordinary_question_release: end_turn=', session.end_turn.await_count, 'close=', session.close.await_count, 'reset_reason=', repr(session.reset_reason))

    with tempfile.TemporaryDirectory() as temp:
        service = BrowserService(Path(temp) / 'artifacts')
        service.configure('private', False)
        service.workbench = {'test': True}
        async def attach(run): run.native = True; run.session = object(); return True
        service._attach_workbench = attach
        run = await service.ensure('private')
        print('persistent_false_still_attaches_native=', run.native)
        shutil.rmtree(run.directory)

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / 'adapters').mkdir(); (root / 'bin').mkdir()
        (root / 'node-path').write_text(shutil.which('node'))
        (root / 'bin/lcu').write_text('fixture')
        shutil.copy('tests/fixtures/cua/client.mjs', root / 'adapters/client.mjs')
        session = CuaSession(CuaConfig(enabled=True, installation=root), root, 'audit')
        session.lease = DesktopLease(root / 'desktop.lock')
        await session.connect()
        tool = CuaTool(session, session.descriptors[0])
        delivery = TaskDelivery(active=True)
        context = ToolContext(root, metadata={'cua_turn_id': 'turn', 'cua_call_id': 'before', 'task_delivery': delivery})
        result = await tool.execute({'code': 'observe-before'}, context)
        if result.success: delivery.evidence.add('tool:before')
        context.metadata['cua_call_id'] = 'uncertain'
        try: await tool.execute({'code': 'crash'}, context)
        except ToolError as exc: print('uncertain_call=', str(exc))
        completed = await FinishTaskTool().execute({'status': 'completed', 'answer': 'Done', 'evidence': ['tool:before'], 'remaining': []}, context)
        print('completed_after_uncertain_call_without_reobservation=', completed.success)
        await session.close()

    with tempfile.TemporaryDirectory() as temp:
        media.user_media_dir = lambda: Path(temp)
        image = Image.frombytes('RGB', (3840, 2160), random.Random(42).randbytes(3840 * 2160 * 3))
        buf = io.BytesIO(); image.save(buf, format='JPEG', quality=95)
        block = media.import_image(buf.getvalue()).model_copy(update={'source': {'kind': 'cua'}})
        wire = media.image_data_url(block)
        payload = base64.b64decode(wire.split(',', 1)[1])
        print('4k_screenshot: input_bytes=', len(buf.getvalue()), 'output_raw_bytes=', len(payload), 'output_base64_bytes=', len(wire.split(',', 1)[1]), 'documented_raw_limit=', media.CUA_RAW_IMAGE_BYTES)

asyncio.run(main())
