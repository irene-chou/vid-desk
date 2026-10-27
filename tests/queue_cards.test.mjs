// 排隊卡片純函式測試：從 index.html 抽出 @@card-fns 區塊（連同它依賴的 @@outputs-state 區塊）直接跑，不經打包。
// 執行：node --test tests/queue_cards.test.mjs（tests/test_static.py 會在有 node 時自動跑）
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, "..", "vid_snatch", "static", "index.html"), "utf8");
const outputsBlock = html.split("// @@outputs-state-begin")[1].split("// @@outputs-state-end")[0];
const cardBlock = html.split("// @@card-fns-begin")[1].split("// @@card-fns-end")[0];
const api = vm.runInThisContext(
  `(function () {\n${outputsBlock}\n${cardBlock}\nreturn { fmtDuration, fmtSize, outputLabel, statusText, timingBase, timingText,
     STATE_ICONS, OUTPUT_STATE_ICONS, OUTPUT_PILL_CLASS, KIND_ICONS, FINISHED_STATES }; })()`,
);

const AUDIO = { audio: { versions: ["original", "instrumental", "vocals"], format: "mp3", bitrate: 192, model: "htdemucs_ft" }, video: null };

test("耗時 m:ss，超過一小時 h:mm:ss", () => {
  assert.equal(api.fmtDuration(41), "0:41");
  assert.equal(api.fmtDuration(134.4), "2:14");
  assert.equal(api.fmtDuration(3661), "1:01:01");
  assert.equal(api.fmtDuration(null), "");
  assert.equal(api.fmtDuration(-3), "0:00");
});

test("檔案大小：小於 10 保留一位小數，否則整數", () => {
  assert.equal(api.fmtSize(512), "512 B");
  assert.equal(api.fmtSize(1258291), "1.2 MB");
  assert.equal(api.fmtSize(12 * 1024 * 1024 + 400000), "12 MB");
  assert.equal(api.fmtSize(3.5 * 1024 ** 3), "3.5 GB");
  assert.equal(api.fmtSize(null), "");
  assert.equal(api.fmtSize(-1), "");
});

test("膠囊文字：版本名 + 尾綴 + 細項摘要；無損不顯示位元率；影片顯示畫質上限", () => {
  assert.equal(api.outputLabel({ kind: "original", ext: "mp3" }, AUDIO), "原曲.mp3 · 192k");
  assert.equal(api.outputLabel({ kind: "instrumental", ext: "mp3" }, AUDIO), "伴奏.mp3 · 192k");
  assert.equal(api.outputLabel({ kind: "vocals", ext: "flac" }, { audio: { ...AUDIO.audio, format: "flac", bitrate: 320 } }), "人聲.flac");
  // 尾綴以 output.ext 為準（m4a 分離結果也是 .m4a）
  assert.equal(api.outputLabel({ kind: "instrumental", ext: "m4a" }, { audio: { ...AUDIO.audio, format: "m4a", bitrate: 320 } }), "伴奏.m4a · 320k");
  assert.equal(api.outputLabel({ kind: "video", ext: "mp4" }, { audio: null, video: { max_height: 1080 } }), ".mp4 · 1080p");
  assert.equal(api.outputLabel({ kind: "video", ext: "mp4" }, { audio: null, video: { max_height: null } }), ".mp4");
  assert.equal(api.outputLabel({ kind: "original", ext: "mp3" }, undefined), "原曲.mp3");
});

test("狀態文字：排隊 #n、進行中與失敗 step/total · 名稱、完成耗時、已取消", () => {
  assert.equal(api.statusText({ state: "queued", queue_position: 2 }), "#2");
  assert.equal(api.statusText({ state: "queued", queue_position: null }), "排隊中");
  assert.equal(api.statusText({ state: "running", step: 2, step_total: 3, step_name: "分離" }), "2/3 · 分離");
  assert.equal(api.statusText({ state: "failed", step: 1, step_total: 3, step_name: "下載" }), "1/3 · 下載");
  assert.equal(api.statusText({ state: "done", elapsed_seconds: 41.2 }), "0:41");
  assert.equal(api.statusText({ state: "done", elapsed_seconds: null }), "完成");
  assert.equal(api.statusText({ state: "cancelled" }), "已取消");
});

test("計時以收到 job 時的 elapsed_seconds 為基準加本機經過時間，不碰 started_at", () => {
  const base = api.timingBase({ elapsed_seconds: 134, eta_seconds: 146, started_at: 1_700_000_000 }, 10_000);
  assert.deepEqual(base, { at: 10_000, elapsed: 134, eta: 146 });
  assert.equal(api.timingText(base, 10_000), "2:14 / ~4:40");
  assert.equal(api.timingText(base, 13_000), "2:17 / ~4:40"); // 預估總時不動，已耗時往上走
  assert.equal(api.timingText(base, 10_000 + 200_000), "5:34 / ~5:34"); // 跑過預估就跟著已耗時
  assert.equal(api.timingText(base, 9_000), "2:14 / ~4:40"); // 本機時間倒退不會變負
});

test("沒有 eta 或剛開始時只顯示已耗時", () => {
  const base = api.timingBase({ elapsed_seconds: null, eta_seconds: null }, 0);
  assert.equal(api.timingText(base, 0), "0:00");
  assert.equal(api.timingText(base, 61_000), "1:01");
  assert.equal(api.timingText(api.timingBase({ elapsed_seconds: 5, eta_seconds: null }, 0), 2_000), "0:07");
});

test("圖示與樣式對照含 cancelled", () => {
  assert.deepEqual(api.STATE_ICONS, { queued: "clock", running: "loader", done: "checkc", failed: "xc", cancelled: "x" });
  assert.deepEqual(api.OUTPUT_STATE_ICONS, { queued: "clock", running: "loader", done: "check", failed: "x" });
  assert.deepEqual(api.OUTPUT_PILL_CLASS, { done: "did", running: "now", failed: "bad" });
  assert.deepEqual(api.KIND_ICONS, { original: "disc", instrumental: "mic-off", vocals: "mic", video: "film" });
  assert.deepEqual(api.FINISHED_STATES, ["done", "failed", "cancelled"]);
});
