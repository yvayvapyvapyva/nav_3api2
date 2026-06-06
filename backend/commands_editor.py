#!/usr/bin/env python3
"""
commands_editor.py — Редактор команд и аудиофайлов

Запуск:  python backend/commands_editor.py
Открыть: http://localhost:8080

Требуется: pip install edge-tts
"""

import asyncio
import json
import os
import re
import unicodedata
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

try:
    import edge_tts
    EDGE_TTS_OK = True
except ImportError:
    EDGE_TTS_OK = False

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / 'assets' / 'js' / 'config.js'
AUDIO_DIR = PROJECT_ROOT / 'audio'

EDGE_TTS_VOICE = 'ru-RU-DmitryNeural'
EDGE_TTS_PITCH = '-10Hz'

# ────────────────────────────── парсинг config.js ──────────────────────────────

def _extract_route_data_js(text):
    match = re.search(r'const\s+ROUTE_DATA\s*=\s*(\{)', text)
    if not match:
        raise ValueError('ROUTE_DATA not found')
    start = match.start(1)
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                if end < len(text) and text[end] == ';':
                    end += 1
                return text[start:end]
    raise ValueError('cannot parse ROUTE_DATA braces')


def _js_obj_to_json(s):
    s = s.strip()
    s = re.sub(r',\s*}', '}', s)
    s = re.sub(r',\s*]', ']', s)
    s = re.sub(r'([{,])\s*([a-zA-Z_]\w*)\s*:', r'\1"\2":', s)
    s = s.replace("'", '"')
    s = s.rstrip(';').strip()
    return s


def parse_config():
    content = CONFIG_PATH.read_text(encoding='utf-8')
    m = re.search(r'const\s+ROUTE_DATA\s*=', content)
    if not m:
        raise ValueError('ROUTE_DATA not found')
    api_config_text = content[:m.start()].rstrip()

    rd_js = _extract_route_data_js(content)
    rd_json = _js_obj_to_json(rd_js)
    route_data = json.loads(rd_json)

    for key, val in route_data.items():
        val['commands'] = [str(c) for c in val.get('commands', [])]
    return api_config_text, route_data


# ──────────────────────────── генерация config.js ─────────────────────────────

def _js_arr(arr):
    items = ', '.join(json.dumps(s, ensure_ascii=False) for s in arr)
    return f'[{items}]'


def _route_data_to_js(data):
    lines = ['const ROUTE_DATA = {']
    keys = list(data.keys())
    for idx, key in enumerate(keys):
        val = data[key]
        lines.append(f"  {key}: {{")
        lines.append(f"    hex: '{val['hex']}', label: '{val['label']}',")
        lines.append(f"    commands: {_js_arr(val['commands'])}")
        lines.append('  }' + (',' if idx < len(keys) - 1 else ''))
    lines.append('};')
    return '\n'.join(lines)


def generate_config(api_config_text, route_data):
    lines = [api_config_text, '']
    lines.append(_route_data_to_js(route_data))
    lines.extend([
        '',
        'const COLORS = Object.fromEntries(',
        '  Object.entries(ROUTE_DATA).map(([k, v]) => [k, { hex: v.hex, label: v.label }])',
        ');',
        '',
        'const COMMAND_SETS = Object.fromEntries(',
        '  Object.entries(ROUTE_DATA).map(([k, v]) => [k, [...v.commands]])',
        ');',
        '',
        "const ALL_AUDIO_COMMANDS = [...new Set(Object.values(ROUTE_DATA).flatMap(v => v.commands))];",
    ])
    return '\n'.join(lines)


def save_config(route_data):
    api_config_text, _ = parse_config()
    content = generate_config(api_config_text, route_data)
    CONFIG_PATH.write_text(content, encoding='utf-8')


# ──────────────────────────── работа с аудио ──────────────────────────────────

def command_to_filename(text):
    if not text:
        return None
    normalized = unicodedata.normalize('NFC', text).lower()
    normalized = re.sub(r'[.,/#!$%^&*;:{}=\-`~()]', '', normalized).strip()
    normalized = re.sub(r'\s+', '_', normalized)
    return normalized + '.mp3'


def command_to_url(text):
    name = command_to_filename(text)
    if not name:
        return None
    return '/audio/' + urllib.parse.quote(name)


def audio_exists(text):
    name = command_to_filename(text)
    if not name:
        return False
    return (AUDIO_DIR / name).is_file()


def delete_audio(text):
    name = command_to_filename(text)
    if not name:
        return False
    path = AUDIO_DIR / name
    if path.exists():
        path.unlink()
        return True
    return False


async def generate_audio(text, pitch=None):
    if not EDGE_TTS_OK:
        raise RuntimeError('edge-tts not installed (pip install edge-tts)')
    name = command_to_filename(text)
    if not name:
        raise ValueError('invalid command text')
    output = AUDIO_DIR / name
    tts = edge_tts.Communicate(text, voice=EDGE_TTS_VOICE, pitch=pitch or EDGE_TTS_PITCH)
    await tts.save(str(output))
    return True


# ──────────────────────────── HTTP-сервер ────────────────────────────────────

PORT = int(os.environ.get('CMD_EDITOR_PORT', 8080))

HTML = r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Редактор команд</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;background:#0f1115;color:#f0f2f5;padding:16px;padding-bottom:80px}
h1{font-size:22px;font-weight:700;margin-bottom:4px}
.sub{color:#888;font-size:13px;margin-bottom:16px}
.btn{padding:10px 18px;border-radius:12px;border:none;font-size:14px;font-weight:600;cursor:pointer;transition:.15s;display:inline-flex;align-items:center;gap:6px}
.btn:active{transform:scale(.96)}
.btn-primary{background:#0A84FF;color:#fff}
.btn-primary:active{background:#0066CC}
.btn-danger{background:#FF453A;color:#fff}
.btn-danger:active{background:#CC332A}
.btn-success{background:#30D158;color:#fff}
.btn-success:active{background:#248A3E}
.btn-small{padding:6px 10px;font-size:12px;border-radius:8px}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid rgba(255,255,255,.08)}
.cat{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.1);border-radius:16px;margin-bottom:12px;overflow:hidden}
.cat-header{display:flex;align-items:center;gap:10px;padding:14px 16px;cursor:pointer;user-select:none}
.cat-header .swatch{width:20px;height:20px;border-radius:50%;border:2px solid rgba(255,255,255,.2);flex-shrink:0}
.cat-header .name{font-size:15px;font-weight:600;flex:1}
.cat-header .count{color:#888;font-size:13px}
.cat-body{display:block;padding:0 16px 14px;border-top:1px solid rgba(255,255,255,.06)}
.cat-edit{display:flex;align-items:center;gap:8px;margin-bottom:10px;padding:8px 0}
.cat-edit input[type=color]{width:32px;height:32px;border:none;border-radius:8px;cursor:pointer;background:transparent;padding:0;flex-shrink:0}
.cat-edit input[type=text]{flex:1;padding:8px 12px;border-radius:10px;border:1px solid rgba(255,255,255,.15);background:rgba(0,0,0,.3);color:#fff;font-size:14px;outline:none}
.cat-edit input[type=text]:focus{border-color:#0A84FF}
.cmd-list{display:flex;flex-direction:column;gap:6px}
.cmd-row{display:flex;align-items:center;gap:6px;padding:8px 10px;background:rgba(255,255,255,.03);border-radius:10px;transition:.15s}
.cmd-row:hover{background:rgba(255,255,255,.06)}
.cmd-row input{flex:1;padding:6px 10px;border-radius:8px;border:1px solid rgba(255,255,255,.12);background:rgba(0,0,0,.3);color:#fff;font-size:13px;outline:none;min-width:0}
.cmd-row input:focus{border-color:#0A84FF}
.cmd-row .status{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.cmd-row .status.ok{background:#30D158}
.cmd-row .status.miss{background:#FF453A}
.cmd-row .icon-btn{background:transparent;border:none;color:#888;cursor:pointer;padding:4px;border-radius:6px;font-size:14px;line-height:1;transition:.15s}
.cmd-row .icon-btn:hover{background:rgba(255,255,255,.1);color:#fff}
.cmd-row .icon-btn.play{color:#5AC8FA}
.cmd-row .icon-btn.gen{color:#FFD700}
.cmd-row .icon-btn.del{color:#FF453A}
.add-cmd{display:flex;gap:6px;margin-top:6px}
.add-cmd input{flex:1;padding:8px 12px;border-radius:10px;border:1px solid rgba(255,255,255,.12);background:rgba(0,0,0,.3);color:#fff;font-size:13px;outline:none}
.add-cmd input:focus{border-color:#30D158}
.add-cat-btn{display:flex;align-items:center;gap:8px;width:100%;padding:14px;border-radius:14px;border:1.5px dashed rgba(255,255,255,.15);background:transparent;color:#888;font-size:14px;font-weight:600;cursor:pointer;transition:.15s;justify-content:center}
.add-cat-btn:hover{border-color:#0A84FF;color:#0A84FF}
.toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%) translateY(100px);padding:12px 24px;border-radius:100px;font-size:14px;font-weight:600;z-index:999;opacity:0;transition:.3s;pointer-events:none}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
.toast.ok{background:rgba(48,209,88,.85);color:#fff}
.toast.err{background:rgba(255,69,58,.85);color:#fff}
.toast.info{background:rgba(10,132,255,.85);color:#fff}
</style>
</head>
<body>

<h1>✏️ Редактор команд</h1>
<div class="sub">config.js + аудиофайлы в папке audio/</div>

<div class="toolbar">
  <button class="btn btn-primary" onclick="saveConfig()">💾 Сохранить config.js</button>

  <span style="flex:1"></span>
  <button class="btn btn-small" onclick="addCategory()" style="background:rgba(255,255,255,.08);color:#fff">➕ Категория</button>
</div>

<div id="app"></div>

<div id="toast" class="toast"></div>

<script>
const COLORS = ['#FFD700','#007AFF','#FF3B30','#AF52DE','#FF9500','#5856D6','#5AC8FA','#A2845E','#34C759','#FF6482','#BF5AF2','#FF9F0A','#64D2FF'];

let data = null;
let audioStatus = {};

function msg(text,type='info'){const t=document.getElementById('toast');t.textContent=text;t.className='toast show '+type;setTimeout(()=>t.className='toast',2500)}

async function load(){
  try{
    const r=await fetch('/api/config');
    data=await r.json();
    await refreshAudioStatus();
    render();
  }catch(e){msg('Ошибка загрузки: '+e.message,'err')}
}

async function refreshAudioStatus(){
  try{const r=await fetch('/api/audio-status',{method:'POST',body:JSON.stringify(data)});audioStatus=await r.json()}catch(e){}
  render();
}

function render(){
  if(!data)return;
  const root=document.getElementById('app');
  let keys=Object.keys(data);
  let html='';
  for(let k of keys){
    const c=data[k];
    const hasAud=audioStatus[k]||{};
    const countAll=c.commands.length;
    const countOk=c.commands.filter(t=>hasAud[t]).length;
    html+=`
      <div class="cat" data-key="${k}">
        <div class="cat-header">
          <div class="swatch" style="background:${c.hex}"></div>
          <div class="name">${esc(c.label)}</div>
          <div class="count">${countOk}/${countAll}</div>
        </div>
        <div class="cat-body">
          <div class="cat-edit">
            <input type="color" value="${c.hex}" onchange="updateCat('${k}','hex',this.value)">
            <input type="text" value="${esc(c.label)}" onchange="updateCat('${k}','label',this.value)" placeholder="Название категории">
            <button class="btn btn-small btn-danger" onclick="deleteCategory('${k}')">✕</button>
          </div>
          <div class="cmd-list" id="cmds-${k}">
            ${c.commands.map((t,i)=>renderCmdRow(k,t,i,hasAud[t])).join('')}
          </div>
          <div class="add-cmd">
            <input type="text" placeholder="Новая команда..." id="newcmd-${k}" onkeydown="if(event.key==='Enter')addCmd('${k}')">
            <button class="btn btn-small btn-success" onclick="addCmd('${k}')">+</button>
          </div>
        </div>
      </div>`;
  }
  html+=`<button class="add-cat-btn" onclick="addCategory()">➕ Добавить категорию</button>`;
  root.innerHTML=html;
}

function renderCmdRow(key,text,idx,hasAudio){
  return `<div class="cmd-row">
    <div class="status ${hasAudio?'ok':'miss'}"></div>
    <input type="text" value="${esc(text)}" onchange="updateCmd('${key}',${idx},this.value)" onfocus="this._val=this.value" onblur="if(this._val!==this.value)refreshAudioStatus()">
    <button class="icon-btn play" onclick="playAudio('${key}',${idx})" ${hasAudio?'':'disabled style="opacity:.3"'}>▶</button>
    <button class="icon-btn gen" onclick="genAudio('${key}',${idx})" title="Сгенерировать MP3">✨</button>
    <button class="icon-btn del" onclick="deleteAudio('${key}',${idx})" ${hasAudio?'':'disabled style="opacity:.3"'}>🗑</button>
    <button class="icon-btn" onclick="deleteCmd('${key}',${idx})" style="color:#FF453A">✕</button>
  </div>`;
}

function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}

function updateCat(key,field,val){
  if(field==='hex')data[key].hex=val;
  else data[key].label=val;
}

function updateCmd(key,idx,val){
  data[key].commands[idx]=val;
}

function addCmd(key){
  const inp=document.getElementById('newcmd-'+key);
  const t=inp.value.trim();
  if(!t)return;
  data[key].commands.push(t);
  inp.value='';
  refreshAudioStatus();
}

function deleteCmd(key,idx){
  if(!confirm('Удалить команду?'))return;
  data[key].commands.splice(idx,1);
  refreshAudioStatus();
}

function addCategory(){
  const name=prompt('Название категории:');
  if(!name)return;
  const key='Cat'+Date.now();
  const used=Object.values(data).map(c=>c.hex);
  const hex=COLORS.find(h=>!used.includes(h))||'#'+Math.floor(Math.random()*0xFFFFFF).toString(16).padStart(6,'0');
  data[key]={hex,label:name,commands:[]};
  render();
}

function deleteCategory(key){
  if(!confirm(`Удалить категорию "${data[key].label}"?`))return;
  delete data[key];
  render();
}

async function playAudio(key,idx){
  const t=data[key].commands[idx];
  if(!t)return;
  const r=await fetch('/api/audio-url?text='+encodeURIComponent(t));
  const j=await r.json();
  if(!j.url){msg('Аудиофайл не найден','err');return}
  const a=new Audio(j.url);
  a.play().catch(e=>msg('Ошибка воспроизведения','err'));
}

async function genAudio(key,idx){
  const t=data[key].commands[idx];
  if(!t)return;
  try{
    const r=await fetch('/api/generate-audio',{method:'POST',body:JSON.stringify({text:t})});
    const j=await r.json();
    if(j.ok){msg('MP3 создан','ok')}
    else msg(j.error||'Ошибка','err');
  }catch(e){msg(e.message,'err')}
  refreshAudioStatus();
}

async function deleteAudio(key,idx){
  const t=data[key].commands[idx];
  if(!t||!confirm(`Удалить аудиофайл для "${t}"?`))return;
  const r=await fetch('/api/delete-audio',{method:'POST',body:JSON.stringify({text:t})});
  const j=await r.json();
  if(j.ok){msg('Аудио удалён','info');refreshAudioStatus()}
  else msg(j.error||'Ошибка','err');
}

async function saveConfig(){
  const btn=event.target;
  btn.textContent='⏳ Сохраняю...';
  btn.disabled=true;
  try{
    const r=await fetch('/api/save',{method:'POST',body:JSON.stringify(data)});
    const j=await r.json();
    if(j.ok){
      msg('config.js сохранён!','ok');
      btn.textContent='💾 Сохранить config.js';
      btn.disabled=false;
    } else {
      msg(j.error||'Ошибка','err');
      btn.textContent='💾 Сохранить config.js';
      btn.disabled=false;
    }
  }catch(e){
    msg(e.message,'err');
    btn.textContent='💾 Сохранить config.js';
    btn.disabled=false;
  }
}

load();
</script>
</body>
</html>'''


class Handler(BaseHTTPRequestHandler):

    def _send(self, data, status=200, ctype='application/json'):
        body = data.encode('utf-8') if isinstance(data, str) else data
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(json.dumps(obj, ensure_ascii=False), status)

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return self.rfile.read(length).decode('utf-8') if length else '{}'

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path == '/':
            self._send(HTML, ctype='text/html; charset=utf-8')
        elif path == '/api/config':
            try:
                _, data = parse_config()
                self._json(data)
            except Exception as e:
                self._json({'error': str(e)}, 500)
        elif path == '/api/audio-url':
            text = (params.get('text') or [''])[0]
            url = command_to_url(text)
            if url and audio_exists(text):
                self._json({'url': url})
            else:
                self._json({'url': None}, 404)
        elif path.startswith('/audio/'):
            filename = urllib.parse.unquote(path[7:])
            safe = os.path.basename(filename)
            filepath = AUDIO_DIR / safe
            if filepath.is_file():
                self._send(filepath.read_bytes(), ctype='audio/mpeg')
            else:
                self._json({'error': 'not found'}, 404)
        else:
            self._json({'error': 'not found'}, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == '/api/audio-status':
            raw = self._read_body()
            body = json.loads(raw) if raw else {}
            result = {}
            for key, val in body.items():
                result[key] = {}
                for cmd in val.get('commands', []):
                    result[key][cmd] = audio_exists(cmd)
            self._json(result)

        elif parsed.path == '/api/save':
            try:
                body = json.loads(self._read_body())
                save_config(body)
                self._json({'ok': True})
            except Exception as e:
                self._json({'error': str(e)}, 500)

        elif parsed.path == '/api/generate-audio':
            body = json.loads(self._read_body())
            text = body.get('text', '')
            if not text:
                self._json({'error': 'empty text'}, 400)
                return
            if not EDGE_TTS_OK:
                self._json({'error': 'edge-tts not installed (pip install edge-tts)'}, 500)
                return
            pitch = body.get('pitch', EDGE_TTS_PITCH)
            try:
                asyncio.run(generate_audio(text, pitch))
                self._json({'ok': True})
            except Exception as e:
                self._json({'error': str(e)}, 500)

        elif parsed.path == '/api/delete-audio':
            body = json.loads(self._read_body())
            text = body.get('text', '')
            if not text:
                self._json({'error': 'empty text'}, 400)
                return
            try:
                ok = delete_audio(text)
                self._json({'ok': ok})
            except Exception as e:
                self._json({'error': str(e)}, 500)

        else:
            self._json({'error': 'not found'}, 404)


def run_server():
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f'  ▶  http://localhost:{PORT}')
    print(f'  ▶  Откройте в браузере (Edge для генерации MP3)')
    if not EDGE_TTS_OK:
        print(f'  ⚠  edge-tts не установлен — генерация MP3 недоступна')
        print(f'     pip install edge-tts')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == '__main__':
    run_server()
