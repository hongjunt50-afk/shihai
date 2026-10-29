// zcode/_selftest.mjs — hook.mjs 的两处真逻辑: 合成消息过滤 + 游标语义。
//
//   node zcode/_selftest.mjs
//
// 这两条一旦错了, 症状都是"静默"的: 过滤失效 → 宿主每轮几千字的合成消息被
// 当经历入库; 游标语义错 → 一天里几十个短回合全部消失。所以必须有可跑的检查。
import { execFile } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { DatabaseSync } = require('node:sqlite');

const SID = 'session_SELFTEST';
const home = mkdtempSync(join(tmpdir(), 'shihai-selftest-home-'));
const dbPath = join(mkdtempSync(join(tmpdir(), 'shihai-selftest-db-')), 'db.sqlite');

const db = new DatabaseSync(dbPath);
db.exec(`
  CREATE TABLE message(id TEXT PRIMARY KEY, session_id TEXT, time_created INT, data TEXT, sequence INT);
  CREATE TABLE part(id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT, time_created INT, data TEXT);
`);
const add = (seq, role, text, synthetic = false) => {
  const mid = `m${seq}`;
  const meta = synthetic ? { role, synthetic: true } : { role };
  db.prepare('INSERT INTO message VALUES (?,?,?,?,?)').run(mid, SID, 0, JSON.stringify(meta), seq);
  db.prepare('INSERT INTO part VALUES (?,?,?,?,?)')
    .run(`p${seq}`, mid, SID, 0, JSON.stringify({ type: 'text', text }));
};
// 第 1 轮: 正文太短, 但夹着一条几万字的合成消息
add(1, 'user', '短内容'.repeat(40));
add(2, 'user', '合成注入'.repeat(5000), true);
add(3, 'assistant', '短回复'.repeat(40));
db.close();

const env = { ...process.env, SHIHAI_HOME: home, ZCODE_DB: dbPath };
const stop = () => new Promise((resolve) => {
  const child = execFile(process.execPath, [join(HERE, 'hook.mjs'), 'stop'],
    { cwd: dirname(HERE), env, timeout: 30000, windowsHide: true },
    () => resolve());
  child.stdin.end(JSON.stringify({ session_id: SID }));
});

let pass = 0, fail = 0;
const check = (label, cond, extra = '') => {
  if (cond) { pass++; console.log(`  OK   ${label}${extra ? ' | ' + extra : ''}`); }
  else { fail++; console.log(`  FAIL ${label}${extra ? ' | ' + extra : ''}`); }
};

console.log('A) 短回合不入库(且合成消息不算量)');
await stop();
const dbFile = join(home, 'shihai.db');
// 短回合不该写库, 所以第一轮跑完可能连库文件都还没建
const readEvents = () => {
  if (!existsSync(dbFile)) return [];
  const conn = new DatabaseSync(dbFile);
  try { return conn.prepare('SELECT summary FROM events').all().map((r) => String(r.summary)); }
  finally { conn.close(); }
};
check('没有写入任何事件', readEvents().length === 0, `events=${readEvents().length}`);

console.log('\nB) 攒够后连第 1 轮的内容一起入库');
const db2 = new DatabaseSync(dbPath);
for (const [seq, role, text] of [[4, 'user', '第二轮用户'.repeat(80)], [5, 'assistant', '第二轮回复'.repeat(80)]]) {
  const mid = `m${seq}`;
  db2.prepare('INSERT INTO message VALUES (?,?,?,?,?)').run(mid, SID, 0, JSON.stringify({ role }), seq);
  db2.prepare('INSERT INTO part VALUES (?,?,?,?,?)')
    .run(`p${seq}`, mid, SID, 0, JSON.stringify({ type: 'text', text }));
}
db2.close();
await stop();
const after = readEvents();
const text = after[0] || '';
check('写入了 1 条事件', after.length === 1, `events=${after.length}`);
check('带上了第 1 轮的短内容(游标未提前推进)', text.includes('短内容'));
check('没有把合成消息当经历', !text.includes('合成注入'));

console.log('\nC) 冷却窗口内不重复入库');
await stop();
check('仍然是 1 条', readEvents().length === 1, `events=${readEvents().length}`);

const state = JSON.parse(readFileSync(join(HERE, 'state', `${SID}.json`), 'utf8'));
check('游标停在最后一条消息', Number(state.seq) === 5, JSON.stringify(state));

console.log(`\n结果：${pass} 通过 / ${fail} 失败`);
process.exit(fail === 0 ? 0 : 1);
