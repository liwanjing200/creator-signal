#!/usr/bin/env node
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const options = Object.fromEntries(process.argv.slice(2).reduce((rows, item, index, all) => item.startsWith("--") ? [...rows, [item.slice(2), all[index + 1]]] : rows, []));
if (!options.url) throw new Error("--url is required");
const maxPosts = Number(options["max-posts"] || 3);

function portOpen(port) {
  return new Promise((resolve) => {
    const socket = net.createConnection(port, "127.0.0.1");
    const timer = setTimeout(() => { socket.destroy(); resolve(false); }, 800);
    socket.once("connect", () => { clearTimeout(timer); socket.destroy(); resolve(true); });
    socket.once("error", () => { clearTimeout(timer); resolve(false); });
  });
}

async function endpoint(explicit) {
  if (explicit?.startsWith("ws")) return explicit;
  if (explicit?.startsWith("http")) {
    try {
      const response = await fetch(`${explicit.replace(/\/$/, "")}/json/version`);
      return (await response.json()).webSocketDebuggerUrl;
    } catch { /* discover Chrome's current port below */ }
  }
  for (const file of [path.join(os.homedir(), "Library/Application Support/Google/Chrome/DevToolsActivePort"), path.join(os.homedir(), "Library/Application Support/Chromium/DevToolsActivePort")]) {
    try {
      const [portText, wsPath] = fs.readFileSync(file, "utf8").trim().split(/\r?\n/);
      if (await portOpen(Number(portText))) return `ws://127.0.0.1:${portText}${wsPath}`;
    } catch { /* try next */ }
  }
  throw new Error("Chrome 远程调试未开启，请打开 chrome://inspect/#remote-debugging 并启用。");
}

class CDP {
  constructor(url) { this.url = url; this.id = 0; this.pending = new Map(); }
  async connect() {
    this.ws = new WebSocket(this.url);
    await new Promise((resolve, reject) => {
      this.ws.addEventListener("open", resolve, { once: true });
      this.ws.addEventListener("error", () => reject(new Error("Chrome CDP 连接失败")), { once: true });
    });
    this.ws.addEventListener("message", (event) => {
      const message = JSON.parse(typeof event.data === "string" ? event.data : Buffer.from(event.data).toString("utf8"));
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message)); else pending.resolve(message.result);
    });
  }
  send(method, params = {}, sessionId) {
    return new Promise((resolve, reject) => {
      const id = ++this.id; this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
      setTimeout(() => { if (this.pending.delete(id)) reject(new Error(`${method} 超时`)); }, 45000);
    });
  }
  close() { this.ws?.close(); }
}

async function evaluate(cdp, sessionId, source) {
  const result = await cdp.send("Runtime.evaluate", { expression: `(${source})()`, awaitPromise: true, returnByValue: true }, sessionId);
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "X 页面读取失败");
  return result.result?.value;
}

function readPage() {
  const profile = location.pathname.split("/").filter(Boolean)[0];
  const metric = (label, name) => {
    const match = String(label || "").match(new RegExp(`(\\d[\\d,]*)\\s+${name}`, "i"));
    return match ? Number(match[1].replaceAll(",", "")) : null;
  };
  const posts = [];
  for (const article of document.querySelectorAll("article")) {
    const link = Array.from(article.querySelectorAll('a[href*="/status/"]')).find((node) => new RegExp(`^/${profile}/status/\\d+`, "i").test(node.getAttribute("href") || ""));
    const href = link?.getAttribute("href");
    const id = href?.match(/status\/(\d+)/)?.[1];
    const raw = article.querySelector('[data-testid="tweetText"]')?.innerText?.trim();
    if (!id || !raw) continue;
    const english = raw.split(/\n+/).map((line) => line.trim()).filter((line) => line && !/[\u4e00-\u9fff]/.test(line));
    const label = article.querySelector('[role="group"]')?.getAttribute("aria-label") || "";
    const image = Array.from(article.querySelectorAll("img")).find((item) => (item.src || "").includes("pbs.twimg.com/media"));
    posts.push({ id, text: english.join("\n") || raw, url: `https://x.com${href}`, created_at: article.querySelector("time")?.getAttribute("datetime") || null,
      cover_url: image?.src || null, is_pinned: /Pinned|置顶/.test(article.innerText), reply_count: metric(label, "repl"), repost_count: metric(label, "repost"),
      like_count: metric(label, "like"), bookmark_count: metric(label, "bookmark"), view_count: metric(label, "view") });
  }
  const follower = document.querySelector(`a[href="/${profile}/verified_followers"]`)?.innerText || document.querySelector(`a[href="/${profile}/followers"]`)?.innerText || null;
  const userId = Array.from(document.querySelectorAll('a[href*="user_id="]')).map((item) => item.href.match(/user_id=(\d+)/)?.[1]).find(Boolean) || null;
  window.scrollBy(0, 1000);
  return { profile, follower, user_id: userId, posts };
}

const cdp = new CDP(await endpoint(options.endpoint || process.env.CHROME_CDP_URL));
let targetId;
try {
  await cdp.connect();
  targetId = (await cdp.send("Target.createTarget", { url: options.url })).targetId;
  const sessionId = (await cdp.send("Target.attachToTarget", { targetId, flatten: true })).sessionId;
  await cdp.send("Runtime.enable", {}, sessionId); await cdp.send("Page.enable", {}, sessionId); await sleep(3500);
  const found = new Map(); let profile = null; let follower = null; let userId = null;
  for (let index = 0; index < 8 && found.size < maxPosts; index++) {
    const page = await evaluate(cdp, sessionId, readPage.toString());
    profile ||= page.profile; follower ||= page.follower; userId ||= page.user_id;
    for (const post of page.posts) found.set(post.id, post);
    await sleep(900);
  }
  process.stdout.write(JSON.stringify({ username: profile, follower_text: follower, user_id: userId, posts: [...found.values()].slice(0, maxPosts) }));
} finally {
  if (targetId) await cdp.send("Target.closeTarget", { targetId }).catch(() => {});
  cdp.close();
}
