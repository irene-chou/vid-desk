// 主題（#26 / #37）純函式測試：從 index.html <head> 抽出 @@theme 區塊直接跑，不經打包。
// 執行：node --test tests/theme.test.mjs（tests/test_static.py 會在有 node 時自動跑）
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, "..", "vid_desk", "static", "index.html"), "utf8");
const block = html.split("// @@theme-begin")[1].split("// @@theme-end")[0];
const api = vm.runInThisContext(
  `(function () {\n${block}\nreturn { THEME_KEY, THEMES, parseTheme, resolveTheme, nextTheme, readTheme, writeTheme, applyTheme }; })()`,
);

// 假 localStorage：只記一個 Map
function fakeStorage(initial = {}) {
  const map = new Map(Object.entries(initial));
  return {
    map,
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => { map.set(k, String(v)); },
    removeItem: (k) => { map.delete(k); },
  };
}

// 假 <html>：只記 data-theme
function fakeRoot() {
  const attrs = new Map();
  return {
    attrs,
    getAttribute: (k) => (attrs.has(k) ? attrs.get(k) : null),
    setAttribute: (k, v) => { attrs.set(k, v); },
    removeAttribute: (k) => { attrs.delete(k); },
  };
}

test("key 與三個選項固定", () => {
  assert.equal(api.THEME_KEY, "vid-desk.theme");
  assert.deepEqual(api.THEMES, ["system", "light", "dark"]);
});

test("parseTheme：合法值原樣回傳，其餘（含 null / 空字串 / 大小寫不同）都當跟隨系統", () => {
  for (const v of ["system", "light", "dark"]) assert.equal(api.parseTheme(v), v);
  for (const v of [null, undefined, "", "Dark", "auto", "blue", 0, {}]) assert.equal(api.parseTheme(v), "system");
});

test("resolveTheme：初始值解析——沒手動選過（system / #26 舊值 / 不存在）跟隨系統，選過就固定", () => {
  assert.equal(api.resolveTheme("system", true), "dark");
  assert.equal(api.resolveTheme("system", false), "light");
  assert.equal(api.resolveTheme(api.parseTheme(null), true), "dark");
  assert.equal(api.resolveTheme("light", true), "light");
  assert.equal(api.resolveTheme("light", false), "light");
  assert.equal(api.resolveTheme("dark", true), "dark");
  assert.equal(api.resolveTheme("dark", false), "dark");
});

test("nextTheme：點擊後切到與目前實際顯示相反的主題", () => {
  assert.equal(api.nextTheme("light"), "dark");
  assert.equal(api.nextTheme("dark"), "light");
  // 跟隨系統且系統深色 → 點一下固定淺色；系統淺色 → 固定深色
  assert.equal(api.nextTheme(api.resolveTheme("system", true)), "light");
  assert.equal(api.nextTheme(api.resolveTheme("system", false)), "dark");
});

test("點兩下回到原本的主題，但已固定、不再跟隨系統", () => {
  const storage = fakeStorage();
  const root = fakeRoot();
  let theme = api.readTheme(() => storage);
  for (let i = 0; i < 2; i++) {
    theme = api.nextTheme(api.resolveTheme(theme, true));
    api.applyTheme(root, theme);
    api.writeTheme(() => storage, theme);
  }
  assert.equal(root.getAttribute("data-theme"), "dark");
  assert.deepEqual([...storage.map], [["vid-desk.theme", "dark"]]);
  assert.equal(api.resolveTheme(api.readTheme(() => storage), false), "dark");
});

test("readTheme：讀到存值就用，沒存或存了怪值當跟隨系統", () => {
  assert.equal(api.readTheme(() => fakeStorage({ "vid-desk.theme": "dark" })), "dark");
  assert.equal(api.readTheme(() => fakeStorage({ "vid-desk.theme": "light" })), "light");
  assert.equal(api.readTheme(() => fakeStorage()), "system");
  assert.equal(api.readTheme(() => fakeStorage({ "vid-desk.theme": "neon" })), "system");
});

test("readTheme：localStorage 不可用（取用或 getItem 丟例外）回跟隨系統，不往外拋", () => {
  assert.equal(api.readTheme(() => { throw new DOMException("blocked", "SecurityError"); }), "system");
  assert.equal(api.readTheme(() => ({ getItem() { throw new Error("quota"); } })), "system");
  assert.equal(api.readTheme(() => null), "system");
});

test("writeTheme：淺 / 深色寫入 key；跟隨系統把 key 刪掉", () => {
  const storage = fakeStorage();
  api.writeTheme(() => storage, "dark");
  assert.deepEqual([...storage.map], [["vid-desk.theme", "dark"]]);
  api.writeTheme(() => storage, "light");
  assert.deepEqual([...storage.map], [["vid-desk.theme", "light"]]);
  api.writeTheme(() => storage, "system");
  assert.deepEqual([...storage.map], []);
});

test("writeTheme：localStorage 不可用時安靜略過", () => {
  assert.doesNotThrow(() => api.writeTheme(() => { throw new Error("blocked"); }, "dark"));
  assert.doesNotThrow(() => api.writeTheme(() => ({ setItem() { throw new Error("quota"); }, removeItem() {} }), "dark"));
});

test("applyTheme：淺 / 深色設 data-theme；跟隨系統移除 data-theme", () => {
  const root = fakeRoot();
  api.applyTheme(root, "dark");
  assert.equal(root.getAttribute("data-theme"), "dark");
  api.applyTheme(root, "light");
  assert.equal(root.getAttribute("data-theme"), "light");
  api.applyTheme(root, "system");
  assert.equal(root.getAttribute("data-theme"), null);
});

test("讀→套用來回一致", () => {
  for (const theme of api.THEMES) {
    const storage = fakeStorage();
    const root = fakeRoot();
    api.writeTheme(() => storage, theme);
    api.applyTheme(root, api.readTheme(() => storage));
    assert.equal(root.getAttribute("data-theme"), theme === "system" ? null : theme);
  }
});
