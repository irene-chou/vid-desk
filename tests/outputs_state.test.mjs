// 輸出選項狀態機的純函式測試：從 index.html 抽出 @@outputs-state 區塊直接跑，不經打包。
// 執行：node --test tests/outputs_state.test.mjs（tests/test_static.py 會在有 node 時自動跑）
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, "..", "vid_snatch", "static", "index.html"), "utf8");
const block = html.split("// @@outputs-state-begin")[1].split("// @@outputs-state-end")[0];
// 在同一個 realm 執行，deepEqual 才不會因 prototype 不同而失敗
const api = vm.runInThisContext(
  `(function () {\n${block}\nreturn { defaultOutputState, orderedVersions, needsSeparation, outputsPayload, outputCount,
     audioSummary, videoSummary, startStatus, existsQuery, applySettings }; })()`,
);

const base = () => api.defaultOutputState();

test("預設只勾音檔與原曲，細項為後端預設", () => {
  assert.deepEqual(base(), {
    audio: true, versions: { original: true, instrumental: false, vocals: false },
    format: "mp3", bitrate: 192, model: "htdemucs_ft", video: false, maxHeight: null,
  });
});

test("payload：沒勾的那邊送 null，版本排成 原曲→伴奏→人聲", () => {
  const s = { ...base(), versions: { vocals: true, original: false, instrumental: true } };
  assert.deepEqual(api.outputsPayload(s), {
    audio: { versions: ["instrumental", "vocals"], format: "mp3", bitrate: 192, model: "htdemucs_ft" },
    video: null,
  });
  const v = { ...base(), audio: false, video: true, maxHeight: 1080 };
  assert.deepEqual(api.outputsPayload(v), { audio: null, video: { max_height: 1080 } });
  assert.deepEqual(api.outputsPayload({ ...base(), video: true }).video, { max_height: null });
});

test("檔案數 = 版本數 + 影片", () => {
  assert.equal(api.outputCount(base()), 1);
  const s = { ...base(), video: true, versions: { original: true, instrumental: true, vocals: true } };
  assert.equal(api.outputCount(s), 4);
  assert.equal(api.outputCount({ ...base(), audio: false }), 0);
});

test("摘要文字", () => {
  assert.equal(api.audioSummary(base()), "MP3 192k · 原曲");
  const s = { ...base(), versions: { original: true, instrumental: true, vocals: false } };
  assert.equal(api.audioSummary(s), "MP3 192k · 原曲 + 伴奏");
  assert.equal(api.audioSummary({ ...s, format: "flac", bitrate: 320 }), "FLAC · 原曲 + 伴奏");
  assert.equal(api.audioSummary({ ...base(), versions: {} }), "MP3 192k · 未選版本");
  assert.equal(api.videoSummary(base()), "MP4 · 最佳畫質");
  assert.equal(api.videoSummary({ ...base(), maxHeight: 720 }), "MP4 · 720p");
});

test("開始鈕：沒選輸出或音檔沒勾版本時停用並說明原因", () => {
  assert.deepEqual(api.startStatus(base(), 2), { ok: true, reason: "", files: 2 });
  assert.deepEqual(api.startStatus({ ...base(), audio: false }, 2), { ok: false, reason: "至少要選一種輸出", files: 0 });
  assert.deepEqual(api.startStatus({ ...base(), versions: {} }, 1), { ok: false, reason: "音檔至少要勾一個版本", files: 0 });
  // 音檔沒勾版本但勾了影片，仍然擋住（後端會回 400）
  assert.equal(api.startStatus({ ...base(), versions: {}, video: true }, 1).ok, false);
  assert.equal(api.startStatus({ ...base(), audio: false, video: true }, 3).files, 3);
});

test("分離模型只在勾了伴奏或人聲時有意義", () => {
  assert.equal(api.needsSeparation(base()), false);
  assert.equal(api.needsSeparation({ ...base(), versions: { original: false, instrumental: false, vocals: true } }), true);
});

test("GET /api/exists 的 query", () => {
  assert.equal(api.existsQuery(base(), "song"), "filename=song&versions=original&format=mp3");
  const s = { ...base(), audio: false, video: true };
  assert.equal(api.existsQuery(s, "a b"), "filename=a+b&video=true");
  const both = { ...base(), video: true, versions: { original: true, vocals: true, instrumental: false }, format: "wav" };
  assert.equal(api.existsQuery(both, "x"), "filename=x&versions=original%2Cvocals&format=wav&video=true");
});

test("套用 GET /api/settings：合法值覆寫，不合法維持原值，null 畫質 = 最佳", () => {
  const s = api.applySettings({ ...base(), maxHeight: 720 },
    { audio_format: "flac", audio_bitrate: 320, demucs_model: "htdemucs", video_max_height: null, output_dir: "/x" });
  assert.equal(s.format, "flac"); assert.equal(s.bitrate, 320); assert.equal(s.model, "htdemucs"); assert.equal(s.maxHeight, null);
  const bad = api.applySettings(base(), { audio_format: "ogg", audio_bitrate: 256, demucs_model: "mdx", video_max_height: 480 });
  assert.deepEqual(bad, base());
  // 版本不從設定來
  assert.deepEqual(api.applySettings(base(), { versions: ["vocals"] }).versions, base().versions);
});
