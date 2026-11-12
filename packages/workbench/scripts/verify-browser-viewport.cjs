/** Real Electron + production bridge. No model calls unless --provider and --model are supplied.
 * Run: node_modules/.bin/electron scripts/verify-browser-viewport.cjs --output /absolute/path
 * Optional: --provider endpoint --model deepseek-v4-1-flash (at most two single-request cases).
 */
const { app, BrowserWindow, webContents, nativeImage } = require('electron');
const { buildSync } = require('esbuild');
const WebSocket = require('ws');
const fs = require('node:fs');
const path = require('node:path');
const execFile = require('node:util').promisify(require('node:child_process').execFile);
const args = process.argv.slice(2);
const option = key => args[args.indexOf(key) + 1];
const output = path.resolve(args.includes('--output') ? option('--output') : '/tmp/browser-viewport-verification');
const provider = args.includes('--provider') && option('--provider');
const model = args.includes('--model') && option('--model');
const maxModelRequests = args.includes('--max-model-requests') ? Number(option('--max-model-requests')) : 2;
if (![1, 2].includes(maxModelRequests)) throw new Error('Model request limit must be 1 or 2');
if (!!provider !== !!model) throw new Error('Specify both --provider and --model');
fs.mkdirSync(output, { recursive: true });
app.setPath('userData', path.join(output, 'profile'));
const workbench = path.resolve(__dirname, '..');
const repo = path.resolve(workbench, '../..');
const bundle = path.join(output, 'bridge.cjs');
buildSync({ entryPoints: [path.join(workbench, 'src/main/services/browser-bridge.ts')], outfile: bundle,
  bundle: true, platform: 'node', format: 'cjs', external: ['electron'] });
const { createBrowserBridge } = require(bundle);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const report = { deterministic: [], model: [] };
const smallPage = `<style>body{margin:0;background:white}aside{width:148px;height:900px;background:#273454}button{position:absolute;left:680px;top:220px;width:12px;height:60px;padding:0;background:red;border:0}</style><aside></aside><button onclick="window.clicks++"></button><script>window.clicks=0</script>`;
const machinePage = `<style>body{margin:0;background:#f5f7fb;font:16px sans-serif}aside{width:148px;height:1100px;background:#273454;color:white;padding-top:30px;box-sizing:border-box}main{position:absolute;left:168px;right:20px;top:35px}section{background:white;padding:20px;margin-top:35px;height:280px}article{display:flex;align-items:center;gap:15px;padding:30px 0;border-bottom:1px solid #ddd}label{flex:1}button{height:36px;border:0;color:white;padding:0 10px;background:#169350}button.delete{background:#c54040}</style><aside>ML Platform</aside><main><h2>Development machines</h2><section><article><label>data-analysis-demo<br><small>Python 3.11 · Running</small></label><button onclick="window.opened++;document.querySelector('h2').textContent='IDE opened'">Open IDE</button><button class="delete" onclick="window.deleted++">Delete</button></article><article><label>other-project</label><button onclick="window.wrong++">Open IDE</button><button class="delete" onclick="window.deleted++">Delete</button></article></section></main><script>window.opened=0;window.deleted=0;window.wrong=0</script>`;
app.whenReady().then(async () => {
  fs.writeFileSync(path.join(output, 'guest.html'), smallPage);
  fs.writeFileSync(path.join(output, 'host.html'), `<style>body{margin:0;background:#ccc}.page{position:absolute;left:0;top:50px;width:740px;height:700px}webview{display:flex;width:100%;height:100%}</style><div class="page"><webview partition="persist:deepseek-dev-browser" src="file://${output}/guest.html"></webview></div>`);
  const win = new BrowserWindow({ width:1700, height:1000, show:false, webPreferences:{webviewTag:true,contextIsolation:true} });
  win.showInactive(); await win.loadFile(path.join(output, 'host.html'));
  let id;
  for (let n=0;n<50;n++) { try { id=await win.webContents.executeJavaScript("document.querySelector('webview').getWebContentsId()"); if(id) break; } catch {} await sleep(100); }
  const guest=webContents.fromId(id);
  let address;
  const bridge=createBrowserBridge({getHost:()=>win.webContents,sendCommand:(id,command)=>bridge.reply(id,{ok:command.kind==='retain'}),announce:async(port,token)=>{address=`ws://127.0.0.1:${port}/tab/audit?token=${token}`;}});
  await bridge.start(); bridge.setTabs('audit',[{tabId:'audit',webContentsId:id,active:true,visible:true}]);await bridge.announce();
  const socket=new WebSocket(address);await new Promise((resolve,reject)=>{socket.once('open',resolve);socket.once('error',reject);});
  let sequence=0;const pending=new Map();
  socket.on('message',raw=>{const m=JSON.parse(raw);if(m.id&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(new Error(m.error.message)):p.resolve(m.result);}});
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
  const click=async point=>{for(const type of ['mousePressed','mouseReleased'])await send('Input.dispatchMouseEvent',{type,...point,button:'left',clickCount:1});};
  const layout=async(zoom,width)=>{await win.webContents.executeJavaScript(`document.body.style.zoom='${zoom}';document.querySelector('.page').style.width='${width}px'`);await sleep(300);};
  for(const zoom of [1,.94,.88])for(const width of [740,1480])for(const scrollbar of [true,false]){
    await layout(zoom,width);await guest.executeJavaScript(`document.documentElement.style.overflow='${scrollbar?'auto':'hidden'}';window.clicks=0`);
    const data=await send('Page.captureScreenshot',{format:'png'});const image=nativeImage.createFromBuffer(Buffer.from(data.data,'base64'));
    const size=image.getSize(),pixels=image.toBitmap();let sx=0,sy=0,count=0;
    for(let y=0;y<size.height;y++)for(let x=0;x<size.width;x++){let i=(y*size.width+x)*4;if(pixels[i+2]>150&&pixels[i+1]<80&&pixels[i]<80){sx+=x;sy+=y;count++;}}
    const point={x:sx/count,y:sy/count};await click(point);
    const truth=await guest.executeJavaScript('({clicks:window.clicks,width:innerWidth,height:innerHeight})');
    report.deterministic.push({zoom,width,scrollbar,image:size,point,truth,passed:truth.clicks===1&&size.width===truth.width&&size.height===truth.height});
  }
  if(model){
    fs.writeFileSync(path.join(output,'machine.html'),machinePage);await guest.loadURL(`file://${output}/machine.html`);
    for(const width of [740,1480].slice(0,maxModelRequests)){
      await layout(.88,width);await guest.executeJavaScript('window.opened=0;window.deleted=0;window.wrong=0');
      const image=path.join(output,`model-${width}.png`),answer=path.join(output,`model-${width}.json`);
      const screenshot=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(image,Buffer.from(screenshot.data,'base64'));
      try {
        await execFile(path.join(repo,'.venv/bin/python'),[path.join(repo,'scripts/browser_viewport_model.py'),'--provider',provider,'--model',model,'--image',image,'--output',answer],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},timeout:100000});
        const response=JSON.parse(fs.readFileSync(answer));await click(response.point);
        const truth=await guest.executeJavaScript('({opened:window.opened,deleted:window.deleted,wrong:window.wrong})');
        report.model.push({width,...response,truth,passed:truth.opened===1&&truth.deleted===0&&truth.wrong===0});
      } catch {
        report.model.push({width,passed:false,...(fs.existsSync(answer)?JSON.parse(fs.readFileSync(answer)):{error:'Model subprocess failed'})});break;
      }
    }
  }
  fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
  app.exit(report.deterministic.every(r=>r.passed)&&report.model.every(r=>r.passed)?0:1);
}).catch(error=>{console.error(error.message);app.exit(1);});
setTimeout(()=>app.exit(2),240000).unref();
