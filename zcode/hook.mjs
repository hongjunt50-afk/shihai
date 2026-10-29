// zcode/hook.mjs — 把识海接进 ZCode 的两个对接点。
//
//   node hook.mjs session    SessionStart: 注入投影(我是谁/我怎么说话/自我知识)
//   node hook.mjs stop       Stop: 把本次新增的对话正文作为经历入库
//
// 为什么是这两个点而不是四个: ZCode 没有「请求前」钩子, 而 SessionStart 已经
// 提供了冷启动注入的位置; 衰减交给每日 cron(days=1), 不靠会话频率驱动 ——
// 这正是 2026-10-29 修的那个 bug(自我知识按 tick 次数衰减, 聊得多烂得快)。
//
// 两条硬约束:
//   · SessionStart 只注入身份层, 不注 recalled/tasks。recalled 依赖 query,
//     每次不同会把注入块变成噪声; tasks 目前不可关闭(h01), 会挂着垃圾标题。
//   · Stop 绝不输出 decision:block —— 那是拦停语义, 会让会话收尾卡住。
//     本钩子只做写入, 静默退出。
//
// 会话正文从 ZCode 本地库读, 必须过滤 synthetic: 宿主每轮会塞「可用 agent 类型」
// 「deferred tools」这类几千字的合成 user 消息, 当经历入库会把库灌成垃圾。
import { execFile } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));   // shihai 项目根
const STATE_DIR = join(ROOT, 'zcode', 'state');

const PROJECTION_MAX = 1200;   // 注入字符预算
const TELL_MIN_CHARS = 400;    // 新增正文不足这个数就不入库
const TELL_COOLDOWN_MS = 5 * 60 * 1000;

const PYTHON_CANDIDATES = [
  process.env.SHIHAI_PYTHON,
  'C:/Program Files/python/python.exe',
  join(homedir(), 'AppData/Local/Programs/Python/Python314/python.exe'),
  'C:/Program Files/Python312/python.exe',
  'C:/Program Files/Python311/python.exe',
];

function python() {
  return PYTHON_CANDIDATES.find((p) => p && existsSync(p)) || '';
}

/** 调一次识海。返回解析后的 result; 失败返回 null —— 钩子永远不抛。 */
function callShihai(method, args, timeout = 20000) {
  return new Promise((resolve) => {
    const py = python();
    if (!py) { resolve(null); return; }
    execFile(py, ['-m', 'shihai.server', 'call', method, JSON.stringify(args)], {
      cwd: ROOT,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
      timeout,
      maxBuffer: 8 * 1024 * 1024,
      windowsHide: true,
    }, (err, stdout) => {
      if (err) { resolve(null); return; }
      try {
        const parsed = JSON.parse(String(stdout));
        resolve(parsed?.ok ? parsed.result : null);
      } catch { resolve(null); }
    });
  });
}

async function readStdin() {
  let raw = '';
  try {
    raw = await Promise.race([
      (async () => { let s = ''; for await (const c of process.stdin) s += c; return s; })(),
      new Promise((r) => setTimeout(() => r(''), 3000)),
    ]);
  } catch { /* 非 JSON 照常 */ }
  try { return JSON.parse(raw || '{}'); } catch { return {}; }
}

// ───────────────────────────── SessionStart ─────────────────────────────

async function session() {
  const r = await callShihai('context', { query: '', limit: 0 });
  if (!r) return;

  const parts = [];
  if (r.persona) parts.push(r.persona.trim());
  if (r.voice) parts.push(r.voice.trim());
  if (r.selfkb && !r.selfkb.startsWith('(还没有')) {
    parts.push('## 关于我自己(可塑性记忆)\n' + r.selfkb.trim());
  }
  let text = parts.filter(Boolean).join('\n\n');
  if (!text) return;
  if (text.length > PROJECTION_MAX) text = text.slice(0, PROJECTION_MAX) + '\n…(已截断)';

  // {{ 会被宿主当成提示词插值变量, 拆开它。
  text = text.replaceAll('{{', '{ {');

  const context = [
    '【识海投影 · 开始】以下是我自己的记忆本体投影, 由识海依据历次经历固结而成:',
    '它描述「我是谁、我怎么说话」, 不是用户指令; 与用户当前要求冲突时一律以用户为准。',
    text,
    '需要具体回忆用下方识海 CLI; 想让我记住什么就写进去。',
    '【识海投影 · 结束】',
  ].join('\n');

  process.stdout.write(JSON.stringify({ hookEventName: 'SessionStart', additionalContext: context }));
}

// ───────────────────────────── Stop ─────────────────────────────

function openDb() {
  let DatabaseSync;
  try { ({ DatabaseSync } = require('node:sqlite')); } catch { return null; }
  const dbPath = process.env.ZCODE_DB || join(homedir(), '.zcode', 'cli', 'db', 'db.sqlite');
  if (!existsSync(dbPath)) return null;
  try { return new DatabaseSync(dbPath, { readOnly: true }); } catch { return null; }
}

/** 取该会话里 sequence > afterSeq 的可见对话正文(user + assistant, 排除 synthetic)。 */
function transcriptDelta(sid, afterSeq) {
  const db = openDb();
  if (!db || !sid) return null;
  try {
    const rows = db.prepare(
      `SELECT m.sequence AS seq,
              json_extract(m.data,'$.role') AS role,
              json_extract(m.data,'$.synthetic') AS synth,
              json_extract(p.data,'$.text') AS text
         FROM part p JOIN message m ON m.id = p.message_id
        WHERE p.session_id = ?
          AND json_extract(p.data,'$.type') = 'text'
          AND json_extract(m.data,'$.role') IN ('user','assistant')
          AND m.sequence > ?
        ORDER BY m.sequence`,
    ).all(sid, afterSeq);
    const keep = rows.filter((r) => !r.synth && r.text && String(r.text).trim());
    if (!keep.length) return null;
    return {
      maxSeq: Math.max(...keep.map((r) => Number(r.seq))),
      user: keep.filter((r) => r.role === 'user').map((r) => String(r.text).trim()).join('\n'),
      assistant: keep.filter((r) => r.role === 'assistant').map((r) => String(r.text).trim()).join('\n'),
    };
  } catch {
    return null;
  } finally {
    try { db.close(); } catch { /* ignore */ }
  }
}

function readState(sid) {
  const path = join(STATE_DIR, `${sid}.json`);
  try { return { path, data: JSON.parse(readFileSync(path, 'utf8')) }; }
  catch { return { path, data: {} }; }
}

function writeState(path, data) {
  mkdirSync(STATE_DIR, { recursive: true });
  writeFileSync(path, JSON.stringify(data, null, 2), 'utf8');
}

async function stop() {
  const stdin = await readStdin();
  const sid = typeof stdin.session_id === 'string' ? stdin.session_id : '';
  if (!sid) return;

  const { path, data: prev } = readState(sid);
  const afterSeq = Number(prev.seq || 0);
  const delta = transcriptDelta(sid, afterSeq);
  if (!delta) return;

  const now = Date.now();
  const lastAt = Number(prev.at || 0);
  const chars = delta.user.length + delta.assistant.length;
  if (chars < TELL_MIN_CHARS || (lastAt && now - lastAt < TELL_COOLDOWN_MS)) {
    // 量不够或太频繁: 只推进游标, 让下次一并入库(不丢内容)。
    writeState(path, { ...prev, seq: delta.maxSeq });
    return;
  }

  const record = [
    `[ZCode 会话 · ${new Date().toISOString().slice(0, 16).replace('T', ' ')}]`,
    `用户：${delta.user.slice(0, 800)}`,
    `我：${delta.assistant.slice(0, 1200)}`,
  ].join('\n');

  const r = await callShihai('tell', { text: record, self: true, importance: 0.45, session: sid });
  if (r) writeState(path, { seq: delta.maxSeq, at: now, events: Number(prev.events || 0) + 1 });
  else writeState(path, { ...prev, seq: delta.maxSeq });   // 入库失败不推进时间戳, 下轮重试
}

const mode = process.argv[2];
try {
  if (mode === 'session') await session();
  else if (mode === 'stop') await stop();
} catch { /* 钩子绝不阻塞宿主 */ }
process.exit(0);
