#!/usr/bin/env node
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

function args(argv) {
  const out = { maxVideos: 3, waitMs: 3500 };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--url") out.url = argv[++i];
    else if (argv[i] === "--max-videos") out.maxVideos = Number(argv[++i]);
    else if (argv[i] === "--wait-ms") out.waitMs = Number(argv[++i]);
    else if (argv[i] === "--endpoint") out.endpoint = argv[++i];
  }
  if (!out.url) throw new Error("--url is required");
  return out;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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
  const candidates = [
    path.join(os.homedir(), "Library/Application Support/Google/Chrome/DevToolsActivePort"),
    path.join(os.homedir(), "Library/Application Support/Chromium/DevToolsActivePort"),
  ];
  for (const file of candidates) {
    try {
      const [portText, wsPath] = fs.readFileSync(file, "utf8").trim().split(/\r?\n/);
      const port = Number(portText);
      if (port && wsPath && await portOpen(port)) return `ws://127.0.0.1:${port}${wsPath}`;
    } catch { /* try next */ }
  }
  throw new Error("没有找到 Chrome CDP。请在 chrome://inspect/#remote-debugging 开启远程调试。 ");
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
      if (!message.id || !this.pending.has(message.id)) return;
      const pending = this.pending.get(message.id); this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message));
      else pending.resolve(message.result);
    });
  }
  send(method, params = {}, sessionId) {
    return new Promise((resolve, reject) => {
      const id = ++this.id; this.pending.set(id, { resolve, reject });
      const payload = { id, method, params }; if (sessionId) payload.sessionId = sessionId;
      this.ws.send(JSON.stringify(payload));
      setTimeout(() => { if (this.pending.delete(id)) reject(new Error(`${method} 超时`)); }, 45000);
    });
  }
  close() { this.ws?.close(); }
}

async function evaluate(cdp, sessionId, functionBody, values = []) {
  const expression = `(${functionBody.toString()})(...${JSON.stringify(values)})`;
  const result = await cdp.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }, sessionId);
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "页面读取失败");
  return result.result?.value;
}

async function navigate(cdp, sessionId, url, waitMs) {
  await cdp.send("Page.navigate", { url }, sessionId);
  await sleep(waitMs);
}

function profileReader(maxVideos) {
  const numberAfter = (labels) => {
    const text = document.body?.innerText || "";
    for (const label of labels) {
      const match = text.match(new RegExp(`([0-9.]+\\s*[万亿wW]?)\\s*${label}`));
      if (match) return match[1].replace(/\s/g, "");
    }
    return null;
  };
  const cards = [];
  const seen = new Set();
  for (const anchor of document.querySelectorAll('a[href*="/video/"]')) {
    const href = anchor.href || "";
    const id = href.match(/\/video\/(\d+)/)?.[1];
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const image = anchor.querySelector("img");
    const text = (anchor.innerText || anchor.getAttribute("aria-label") || image?.alt || "").trim();
    cards.push({ aweme_id: id, url: href.split("?")[0], title: text.slice(0, 300) || null, cover_url: image?.currentSrc || image?.src || null, is_pinned: /置顶/.test(text) });
    if (cards.length >= maxVideos) break;
  }
  return { follower_text: numberAfter(["粉丝"]), likes_text: numberAfter(["获赞", "获赞与收藏"]), cards };
}

function videoReader() {
  const body = document.body?.innerText || "";
  const descriptionNode = document.querySelector('[data-e2e="video-desc"], [data-e2e*="video-title"], h1');
  const comments = [];
  const seen = new Set();
  for (const node of document.querySelectorAll('[data-e2e*="comment"], [class*="comment-item"], [class*="CommentItem"]')) {
    const text = (node.innerText || "").trim();
    if (!text || text.length > 1000 || seen.has(text)) continue;
    seen.add(text);
    const lines = text.split(/\n+/).map((line) => line.trim()).filter(Boolean);
    comments.push({ author: lines[0] || null, content: (lines.slice(1).join(" ") || lines[0]).slice(0, 800), like_text: lines.find((line) => /^\d+[万wW]?$/.test(line)) || null });
    if (comments.length >= 12) break;
  }
  const chapters = [];
  const chapterPattern = /(?:^|\n)(\d{1,2}:\d{2}(?::\d{2})?)\s+([^\n]{2,100})/g;
  let match;
  while ((match = chapterPattern.exec(body)) && chapters.length < 30) chapters.push({ timestamp: match[1], title: match[2].trim(), description: null });
  const time = body.match(/(?:发布时间[:：]?\s*)?(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2})/)?.[1] || null;
  return { description: (descriptionNode?.innerText || "").trim() || null, published_text: time, comments, chapters };
}

async function main() {
  const options = args(process.argv.slice(2));
  const cdp = new CDP(await endpoint(options.endpoint || process.env.CHROME_CDP_URL));
  let targetId;
  try {
    await cdp.connect();
    targetId = (await cdp.send("Target.createTarget", { url: options.url })).targetId;
    const sessionId = (await cdp.send("Target.attachToTarget", { targetId, flatten: true })).sessionId;
    await cdp.send("Runtime.enable", {}, sessionId); await cdp.send("Page.enable", {}, sessionId);
    await sleep(options.waitMs);
    const profile = await evaluate(cdp, sessionId, profileReader, [options.maxVideos]);
    for (const card of profile.cards) {
      await navigate(cdp, sessionId, card.url, options.waitMs);
      Object.assign(card, await evaluate(cdp, sessionId, videoReader));
    }
    process.stdout.write(JSON.stringify(profile));
  } finally {
    if (targetId) await cdp.send("Target.closeTarget", { targetId }).catch(() => {});
    cdp.close();
  }
}

main().catch((error) => { console.error(error.message); process.exit(1); });
