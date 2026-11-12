"use strict";
// Jarvis phone app. Everything to/from the laptop is AES-256-GCM encrypted with a key that only lives here and on the laptop.
const $ = s => document.querySelector(s);
const log = $("#log"), stateEl = $("#state"), orb = $("#orb");
let S = {}; try { S = JSON.parse(localStorage.getItem("jarvis") || "{}"); } catch (e) {}
const save = () => { try { localStorage.setItem("jarvis", JSON.stringify(S)); } catch (e) {} };
const b64e = u => { let s = ""; u.forEach(c => s += String.fromCharCode(c)); return btoa(s); };
const b64d = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
const b64u = s => b64d(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4));
const enc = new TextEncoder(), dec = new TextDecoder();
let KEY = null, ws = null, online = false, pending = {}, files = {};

async function loadKey() { KEY = await crypto.subtle.importKey("raw", b64u(S.key), "AES-GCM", false, ["encrypt", "decrypt"]); }
async function seal(obj) {
  const n = crypto.getRandomValues(new Uint8Array(12));
  const c = await crypto.subtle.encrypt({ name: "AES-GCM", iv: n, additionalData: enc.encode("p2l") }, KEY, enc.encode(JSON.stringify(obj)));
  return { n: b64e(n), c: b64e(new Uint8Array(c)) };
}
async function open(f) {
  const p = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64d(f.n), additionalData: enc.encode("l2p") }, KEY, b64d(f.c));
  return JSON.parse(dec.decode(p));
}
const uid = () => Array.from(crypto.getRandomValues(new Uint8Array(9)), x => x.toString(16).padStart(2, "0")).join("");
const fmt = t => new Date(t * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const setState = (txt, ok) => { stateEl.textContent = txt; stateEl.className = ok ? "ok" : "off"; };

function add(who, text, ts) {
  const d = document.createElement("div"); d.className = "m" + (who === "You" ? " u" : "");
  const h = document.createElement("div"); h.className = "who"; h.textContent = who.toUpperCase();
  const t = document.createElement("span"); t.className = "ts"; t.textContent = fmt(ts || Date.now() / 1000); h.appendChild(t);
  const b = document.createElement("div"); b.textContent = text;
  d.append(h, b); log.appendChild(d); log.scrollTop = log.scrollHeight; return d;
}
function cards(parent, list) {
  if (!list || !list.length) return;
  const box = document.createElement("div"); box.className = "files";
  list.forEach(f => {
    const c = document.createElement("div"); c.className = "f";
    const info = document.createElement("div");
    const b = document.createElement("b"); b.textContent = f.name;
    const s = document.createElement("small");
    s.textContent = [f.type, f.amount, f.date, f.chat, f.size ? Math.max(1, Math.round(f.size / 1024)) + " KB" : ""].filter(Boolean).join(" · ");
    info.append(b, s);
    const go = document.createElement("div"); go.className = "go";
    const bt = document.createElement("button"); bt.textContent = "OPEN";
    bt.onclick = () => getFile(f, bt); go.appendChild(bt);
    c.append(info, go); box.appendChild(c);
  });
  parent.appendChild(box); log.scrollTop = log.scrollHeight;
}

async function send(obj) { ws.send(JSON.stringify(await seal({ ...obj, ts: Date.now() / 1000 }))); }
function request(obj) { const id = uid(); return new Promise(async (res, rej) => { pending[id] = { res, rej, parts: [] }; try { await send({ ...obj, id }); } catch (e) { delete pending[id]; rej(e); } }); }

async function onMsg(f) {
  let m; try { m = await open(f); } catch (e) { return; }
  const p = pending[m.id];
  if (m.kind === "working") { orb.classList.add("work"); return; }
  if (m.kind === "chunk" && p) {
    p.parts[m.i] = b64d(m.data);
    if (m.last) { delete pending[m.id]; p.res({ name: m.name, mime: m.mime, blob: new Blob(p.parts, { type: m.mime }) }); }
    return;
  }
  if (!p) return;
  delete pending[m.id]; orb.classList.remove("work");
  if (m.kind === "error") p.rej(new Error(m.text)); else p.res(m);
}

function connect() {
  if (!S.token) return;
  const u = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/phone?token=" + encodeURIComponent(S.token);
  ws = new WebSocket(u);
  ws.onopen = () => setState("connecting…", false);
  ws.onmessage = e => { let f; try { f = JSON.parse(e.data); } catch (x) { return; }
    if (f.t === "presence") { online = f.laptop; setState(online ? "your laptop is online" : "laptop offline - is it on and on Wi-Fi?", online); }
    else if (f.t === "msg") onMsg(f);
    else if (f.t === "error") add("Jarvis", "Please slow down a little.");
  };
  ws.onclose = () => { online = false; setState("reconnecting…", false); orb.classList.remove("work"); setTimeout(connect, 2500); };
}

async function ask(text) {
  if (!text.trim()) return;
  add("You", text);
  if (!ws || ws.readyState !== 1) { add("Jarvis", "I can't reach the server right now. Trying again - please retry in a moment."); return; }
  if (!online) { add("Jarvis", "Your laptop is offline. Please check that it is switched on, plugged in and on Wi-Fi."); return; }
  try {
    const r = await request({ kind: "ask", text });
    const d = add("Jarvis", r.text || "(no answer)", r.ts); cards(d, r.files); speak(r.text);
  } catch (e) { add("Jarvis", String(e.message || e)); orb.classList.remove("work"); }
}

async function getFile(f, btn) {
  btn.disabled = true; btn.textContent = "…";
  try {
    const r = await request({ kind: "file", fid: f.fid });
    files[f.fid] = r; show(r);
  } catch (e) { add("Jarvis", String(e.message || e)); }
  btn.disabled = false; btn.textContent = "OPEN";
}
let curUrl = null, cur = null;
function show(r) {
  cur = r; if (curUrl) URL.revokeObjectURL(curUrl);
  curUrl = URL.createObjectURL(r.blob);
  $("#stitle").textContent = r.name; const body = $("#sbody"); body.textContent = "";
  if (r.mime.startsWith("image/")) { const i = document.createElement("img"); i.src = curUrl; body.appendChild(i); }
  else if (r.mime === "application/pdf" || r.mime.startsWith("text/")) { const fr = document.createElement("iframe"); fr.src = curUrl; body.appendChild(fr); }
  else { const p = document.createElement("p"); p.textContent = "This file type can't be previewed. Tap SAVE."; body.appendChild(p); }
  $("#sheet").classList.add("show");
}
$("#sclose").onclick = () => $("#sheet").classList.remove("show");
$("#ssave").onclick = () => { const a = document.createElement("a"); a.href = curUrl; a.download = cur.name; document.body.appendChild(a); a.click(); a.remove(); };
$("#sshare").onclick = async () => {
  try { const f = new File([cur.blob], cur.name, { type: cur.mime }); if (navigator.canShare && navigator.canShare({ files: [f] })) await navigator.share({ files: [f], title: cur.name }); else $("#ssave").click(); } catch (e) {}
};

// voice: speak to ask (Web Speech), and read answers aloud (off by default)
let rec = null, lang = (S.lang || "en-US"), say = !!S.say;
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
$("#mic").onclick = () => {
  if (!SR) { add("Jarvis", "Voice typing isn't available in this browser. Please type, or use the keyboard's microphone."); return; }
  if (rec) { rec.stop(); return; }
  rec = new SR(); rec.lang = lang; rec.interimResults = false;
  rec.onresult = e => { $("#msg").value = e.results[0][0].transcript; $("#form").requestSubmit(); };
  rec.onend = () => { rec = null; $("#mic").classList.remove("on"); };
  rec.onerror = () => {}; $("#mic").classList.add("on"); rec.start();
};
function speak(t) { if (!say || !t || !window.speechSynthesis) return; const u = new SpeechSynthesisUtterance(t.slice(0, 400)); u.lang = lang; speechSynthesis.speak(u); }
$("#more").onclick = async () => {
  const order = ["en-US", "ur-PK", "hi-IN"]; const names = { "en-US": "English", "ur-PK": "Urdu", "hi-IN": "Hindi" };
  lang = order[(order.indexOf(lang) + 1) % 3]; S.lang = lang; save();
  say = !say || lang !== "en-US" ? true : false; S.say = say; save();
  add("Jarvis", "Voice language: " + names[lang] + ". Answers read aloud: " + (say ? "on" : "off") + ". Tap ⋯ again to change.");
};

$("#form").onsubmit = e => { e.preventDefault(); const v = $("#msg").value; $("#msg").value = ""; ask(v); };

async function loadHistory() {
  try { const r = await request({ kind: "history" });
    (r.items || []).forEach(i => add(i.role === "user" ? "You" : "Jarvis", i.text, i.ts)); } catch (e) {}
}

// -------- pairing --------
function pairUI(code) {
  log.innerHTML = "";
  const w = document.createElement("div"); w.id = "welcome";
  w.innerHTML = '<h2 style="color:var(--gold);letter-spacing:3px">CONNECT TO JARVIS</h2><p>On your laptop say <b>"connect my phone"</b>, then scan the QR code with this phone\'s camera, or type the code here.</p>' +
    '<input type="text" id="code" maxlength="8" placeholder="CODE" style="text-transform:uppercase;text-align:center;letter-spacing:6px;width:100%"><p id="perr" style="color:var(--red)"></p><button id="go">CONNECT</button>';
  log.appendChild(w); if (code) $("#code").value = code;
  $("#go").onclick = () => claim($("#code").value);
}
async function claim(code) {
  const hash = new URLSearchParams(location.hash.slice(1)); const k = hash.get("k") || S.pendingKey;
  if (!k) { $("#perr").textContent = "Please scan the QR code on your laptop - it carries the secret key."; return; }
  try {
    const r = await fetch("/api/pair/claim", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, name: (navigator.userAgent.includes("iPhone") ? "iPhone" : navigator.userAgent.includes("Android") ? "Android phone" : "Phone") }) });
    const j = await r.json(); if (!r.ok) throw new Error(j.error || "failed");
    S = { token: j.token, key: k, lang, say }; save(); history.replaceState(null, "", location.pathname);
    start();
  } catch (e) { $("#perr").textContent = e.message; }
}
async function start() {
  log.innerHTML = ""; await loadKey(); connect();
  add("Jarvis", "Hello. Ask me for any document - for example: \"latest invoice dikhao\".");
  const t = setInterval(() => { if (online) { clearInterval(t); loadHistory(); } }, 500); setTimeout(() => clearInterval(t), 8000);
}
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
(async () => {
  const h = new URLSearchParams(location.hash.slice(1));
  if (S.token && S.key) return start();
  if (h.get("k")) S.pendingKey = h.get("k");
  if (h.get("c") && h.get("k")) { pairUI(h.get("c")); claim(h.get("c")); } else pairUI("");
})();
