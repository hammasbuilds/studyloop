"use strict";
/* StudyLoop single-page app. No build step; talks to /api/*. */

const $app = document.getElementById("app");
const state = { settings: null, llm: null, quiz: null, ask: { bookId: null, last: null }, polling: null };

/* ---------- helpers ---------- */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.json !== undefined) { init.body = JSON.stringify(opts.json); init.headers["Content-Type"] = "application/json"; }
  if (opts.form) init.body = opts.form;
  const r = await fetch("/api" + path, init);
  let data = null;
  try { data = await r.json(); } catch (e) { /* no body */ }
  if (!r.ok) throw new Error((data && (data.detail?.[0]?.msg || data.detail)) || r.statusText);
  return data;
}
function toast(msg) {
  const t = document.getElementById("toast"); t.classList.remove("show"); void t.offsetWidth; t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 3200);
}
const pct = (x) => Math.round((x || 0) * 100);
function when(days) {
  if (days == null) return "";
  const a = Math.abs(days), sign = days < 0 ? "ago" : "";
  const txt = a < 1 / 24 ? Math.max(1, Math.round(a * 1440)) + " min" : a < 1 ? Math.round(a * 24) + " h" : (a < 10 ? a.toFixed(1).replace(/\.0$/, "") : Math.round(a)) + " d";
  return days < 0 ? txt + " " + sign : "in " + txt;
}
function dt(ts) { return new Date(ts * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }); }
function pillFor(level) { const k = level === "getting there" ? "getting" : level; return `<span class="pill ${k}">${esc(level)}</span>`; }
function bar(p, big = false) { return `<div class="bar ${big ? "big" : ""}" role="img" aria-label="mastery ${pct(p)} percent"><i style="width:${pct(p)}%"></i><b style="left:95%" title="mastery threshold 95%"></b></div>`; }
const isRTL = (s) => /[؀-ۿ]/.test(s);

/* ---------- markdown (small, safe) ---------- */
const OPEN = "", CLOSE = "";
function inline(s) {
  s = esc(s);
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^\w*])\*([^*\s][^*]*?)\*(?![\w*])/g, "$1<em>$2</em>");
  s = s.replace(/(^|[^\w])_([^_\s][^_]*?)_(?![\w])/g, "$1<em>$2</em>");
  s = s.replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1");
  s = s.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return s;
}
function renderMd(text, hl) {
  let src = text;
  if (hl) {
    const a = Math.max(0, hl[0]), b = Math.min(text.length, hl[1]);
    if (b > a) src = text.slice(0, a) + OPEN + text.slice(a, b) + CLOSE + text.slice(b);
  }
  const lines = src.split("\n"), out = [];
  let i = 0, carry = false;
  const wrap = (html) => {
    if (carry) html = OPEN + html;
    const o = (html.match(//g) || []).length, c = (html.match(//g) || []).length;
    carry = o > c; if (carry) html += CLOSE;
    return html.replaceAll(OPEN, '<mark class="hl">').replaceAll(CLOSE, "</mark>");
  };
  while (i < lines.length) {
    const ln = lines[i];
    if (!ln.trim()) { i++; continue; }
    if (/^\s*(```|~~~)/.test(ln)) {
      const code = []; i++;
      while (i < lines.length && !/^\s*(```|~~~)/.test(lines[i])) code.push(lines[i++]);
      i++; out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`); continue;
    }
    const h = ln.match(/^(#{1,6})\s+(.*)$/);
    if (h) { const n = Math.min(6, h[1].length + 1); out.push(`<h${n}>${wrap(inline(h[2]))}</h${n}>`); i++; continue; }
    if (/^\s*\|/.test(ln)) {
      const rows = []; while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const body = rows.filter((r) => !/^\s*\|?[\s:|-]+\|?\s*$/.test(r));
      out.push("<table>" + body.map((r, k) => "<tr>" + cells(r).map((c) => `<${k ? "td" : "th"}>${inline(c)}</${k ? "td" : "th"}>`).join("") + "</tr>").join("") + "</table>");
      continue;
    }
    if (/^\s*>/.test(ln)) {
      const q = []; while (i < lines.length && /^\s*>/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${wrap(inline(q.join(" ")))}</blockquote>`); continue;
    }
    if (/^\s*([-*+]|\d+[.)])\s+/.test(ln)) {
      const ordered = /^\s*\d/.test(ln), items = [];
      while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*+]|\d+[.)])\s+/, ""));
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag}>${items.map((x) => `<li>${wrap(inline(x))}</li>`).join("")}</${tag}>`); continue;
    }
    if (/^\s*([-*_]\s*){3,}$/.test(ln)) { out.push("<hr>"); i++; continue; }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*(```|~~~)|\s*\|)/.test(lines[i])) para.push(lines[i++]);
    out.push(`<p>${wrap(inline(para.join(" ")))}</p>`);
  }
  return out.join("\n");
}

/* ---------- theme & nav ---------- */
function applyTheme(t) {
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  try { localStorage.setItem("sl-theme", t || "auto"); } catch (e) { /* storage may be blocked */ }
}
document.getElementById("theme").addEventListener("click", async () => {
  const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  const next = dark ? "light" : "dark"; applyTheme(next);
  try { await api("/settings", { method: "PUT", json: { theme: next } }); } catch (e) { /* offline is fine */ }
});
function setActive(name) { document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.r === name)); }

/* ---------- router ---------- */
const routes = [];
const route = (re, name, fn) => routes.push({ re, name, fn });
async function render() {
  clearTimeout(state.polling); state.quiz = null;
  const hash = location.hash.replace(/^#/, "") || "/";
  const [path, qs] = hash.split("?"); const params = new URLSearchParams(qs || "");
  for (const r of routes) {
    const m = path.match(r.re);
    if (m) {
      setActive(r.name); $app.innerHTML = skeleton(3);
      try { await r.fn(m, params); if (!params.get("hl")) window.scrollTo(0, 0); }
      catch (e) { $app.innerHTML = `<div class="card"><h2>Something went wrong</h2><p>${esc(e.message)}</p><a class="btn secondary" href="#/">Back to dashboard</a></div>`; }
      return;
    }
  }
  $app.innerHTML = `<div class="empty"><h2>Page not found</h2><a href="#/">Go to the dashboard</a></div>`;
}
window.addEventListener("hashchange", render);

/* ---------- progress rings & skeletons ---------- */
const RING_C = 2 * Math.PI * 42;
function ringSvg(share, size = 72, label = null) {
  const s = Math.max(0, Math.min(100, share));
  const tone = s >= 100 ? "full" : s >= 50 ? "" : s >= 20 ? "c" : "b";
  return `<div class="ring2 ${s >= 100 ? "full" : ""}" style="--sz:${size}px" role="img" aria-label="${label || "progress"} ${Math.round(s)} percent">
    <svg width="${size}" height="${size}" viewBox="0 0 100 100" aria-hidden="true"><circle class="trk" cx="50" cy="50" r="42"/><circle class="arc ${tone === "full" ? "" : tone}" cx="50" cy="50" r="42" style="stroke-dasharray:${RING_C.toFixed(1)};stroke-dashoffset:${RING_C.toFixed(1)}" data-off="${(RING_C * (1 - s / 100)).toFixed(1)}"/></svg>
    <span class="val">${Math.round(s)}%</span></div>`;
}
function animateRings(root = document) {
  requestAnimationFrame(() => requestAnimationFrame(() => root.querySelectorAll(".ring2 .arc[data-off]").forEach((a) => { a.style.strokeDashoffset = a.dataset.off; })));
}
const skeleton = (n = 3) => `<div class="skel h1"></div>${'<div class="skel block"></div>'.repeat(Math.min(n, 2))}${'<div class="skel line"></div>'.repeat(n)}`;

/* ---------- home hero: the "try it" panel, answered live by this app's own API ---------- */
const TRY_SAMPLE = [
  { label: "Why does a candle flame point upward?", mode: "ask", text: "Why does a candle flame point upward?" },
  { label: "موم بتی کیسے جلتی ہے؟", mode: "ask", text: "موم بتی کیسے جلتی ہے؟" },
  { label: "Quiz me on hydrogen", mode: "quiz", text: "hydrogen" },
  { label: "What is capillary attraction?", mode: "ask", text: "What is capillary attraction?" },
];
function tryExamples(book) {
  if (book.source_type === "sample") return TRY_SAMPLE;
  const ex = (book.suggestions || []).slice(0, 3).map((s) => ({ label: s, mode: "ask", text: s }));
  const first = (book.course || []).flatMap((c) => c.topics)[0];
  if (first) ex.push({ label: "Quiz me on " + first.title, mode: "quiz", text: first.title });
  return ex.length ? ex : TRY_SAMPLE;
}
function heroHtml(book) {
  const copy = `<div class="copy"><span class="eyebrow">&#9728; Your book, your tutor</span>
    <h1>Ask your book anything. <em>Get the quote.</em></h1>
    <p class="lede">StudyLoop answers only from the pages you give it, shows the exact line it came from, and quizzes you until it sticks. Everything below is produced live by this app.</p></div>
    <svg class="mascot" width="96" height="96" viewBox="0 0 32 32" aria-hidden="true"><defs><linearGradient id="slg2" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffffff" stop-opacity=".95"/><stop offset="1" stop-color="#e6dcff"/></linearGradient></defs><rect width="32" height="32" rx="10" fill="url(#slg2)" transform="rotate(8 16 16)"/><g transform="rotate(8 16 16)"><path d="M8.5 16a7.5 7.5 0 1 1 3.2 6.1M8.5 23v-5.5H14" fill="none" stroke="#5b3fd9" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><circle cx="16" cy="16" r="3.2" fill="#ffb627"/><circle cx="24.5" cy="7.5" r="2" fill="#ff6a55"/></g></svg>`;
  if (!book) {
    return `<section class="hero">${copy}<div class="try"><div class="pane in"><div class="tag"><i>1</i> Input</div><p>Load the bundled sample book (Faraday's <em>Chemical History of a Candle</em>) to try it.</p>
      <p><button class="btn coral" id="sample">Load the sample book</button> <a class="btn secondary" href="#/library">Add your own</a></p></div>
      <div class="pane out"><div class="tag"><i>2</i> Output</div><p class="muted">A verified answer with its quote and location appears here.</p></div></div></section>`;
  }
  const ex = tryExamples(book);
  return `<section class="hero" aria-label="Try StudyLoop">${copy}
    <div class="try" id="try">
      <div class="pane in"><div class="tag"><i>1</i> Input <span class="small muted" style="text-transform:none;letter-spacing:0;font-weight:600">from <em>${esc(book.title)}</em></span></div>
        <div class="seg" role="group" aria-label="What to do"><button type="button" data-mode="ask" aria-pressed="true">Ask</button><button type="button" data-mode="quiz" aria-pressed="false">Quiz me</button></div>
        <label for="tryq" id="trylabel">Your question</label>
        <textarea id="tryq" dir="auto" maxlength="300" rows="3">${esc(ex[0].text)}</textarea>
        <div class="chips">${ex.map((e, i) => `<a class="chip" href="#/" data-i="${i}" dir="auto">${esc(e.label)}</a>`).join("")}</div>
        <div class="runrow"><button class="btn coral" id="tryrun">&#9654; Run</button><span class="small muted">Ctrl + Enter</span></div></div>
      <div class="pane out"><div class="tag"><i>2</i> Output <span id="trytime"></span></div><div id="tryout" aria-live="polite"></div></div>
    </div></section>`;
}
function pickTopic(book, text) {
  const words = text.toLowerCase().match(/[a-z]{3,}/g) || [];
  let best = null, bestScore = 0;
  for (const c of book.course || []) for (const t of c.topics) {
    const hay = (t.title + " " + t.concepts.map((x) => x.term).join(" ")).toLowerCase();
    const score = words.reduce((n, w) => n + (hay.includes(w.slice(0, Math.max(4, w.length - 2))) ? (t.title.toLowerCase().includes(w.slice(0, 4)) ? 3 : 1) : 0), 0);
    if (score > bestScore) { best = t; bestScore = score; }
  }
  return best;
}
function tryAnswer(r) {
  const a = r.analysis;
  const read = `<div class="small muted">Read as <strong>${LANG[a.language] || esc(a.language)}</strong>${a.mapped.some((x) => x.how !== "english word") ? ` · ${a.mapped.filter((x) => x.how !== "english word").map((x) => `<span ${isRTL(x.from) ? 'dir="rtl"' : ""}>${esc(x.from)}</span> &rarr; ${esc(x.to)}`).join(", ")}` : ""}</div>`;
  if (!r.answered) {
    return `<div class="anim">${read}<div class="answer-box none" style="margin-top:10px"><strong>The book does not say.</strong> ${esc((r.message || "").replace(/^The book does not say\.\s*/, "") || "No passage covers that question.")}
      ${r.related.length ? `<div class="small" style="margin-top:8px">Closest topics: ${r.related.map((x) => `<a href="#/topic/${x.topic_id}">${esc(x.topic)}</a>`).join(", ")}</div>` : ""}</div></div>`;
  }
  const cs = r.citations.slice(0, 2), llm = r.mode.startsWith("llm");
  return `<div class="anim"><div class="head"><span class="verified">&#10003; Verified in the book</span><span class="small muted">${llm ? "written by " + esc(r.mode.slice(4)) + ", quotes re-checked" : "the book's own sentences, no model"}</span></div>${read}
    <div class="ans" ${isRTL(r.question) ? "" : ""}>${llm ? esc(r.answer) : cs.map((c) => `${esc(c.quote)} <sup>[${c.n}]</sup>`).join(" ")}</div>
    ${cs.map((c) => `<div class="where"><strong>[${c.n}]</strong> ${esc(c.chapter || "")} &rsaquo; ${esc(c.topic || "")} · line ${c.line} · characters ${c.start}&ndash;${c.end} · <a href="#/topic/${c.topic_id}?hl=${c.start}-${c.end}">open in the book &rarr;</a></div>`).join("")}</div>`;
}
function tryQuiz(q, topic) {
  const kinds = { cloze: "Fill in the blank", mcq: "Choose the missing word", tf: "True or false?" };
  const prompt = esc(q.prompt).replace("_____", '<span class="blank">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>');
  const inputs = q.kind === "cloze"
    ? `<div class="row" style="flex-wrap:nowrap"><input type="text" id="tryresp" autocomplete="off" spellcheck="false" placeholder="Type the missing word (${esc(q.hint || "")})" aria-label="answer"><button class="btn small" id="trycheck">Check</button></div>`
    : `<div class="opts">${q.options.map((o, k) => `<button class="opt" data-o="${esc(o)}"><kbd>${k + 1}</kbd>${esc(o[0].toUpperCase() + o.slice(1))}</button>`).join("")}</div>`;
  return `<div class="anim"><div class="head"><span class="pill getting">${esc(kinds[q.kind])}</span><span class="small muted">generated from <a href="#/topic/${topic.id}">${esc(topic.title)}</a></span></div>
    <div class="tq-prompt">${prompt}</div>${inputs}<div id="tryfb"></div></div>`;
}
async function trySubmit(q, topic, val, out) {
  out.querySelectorAll("button, input").forEach((e) => (e.disabled = true));
  try {
    const r = await api("/quiz/answer", { method: "POST", json: { question_id: q.id, response: val } });
    out.querySelectorAll(".opt").forEach((b) => { if (b.dataset.o.toLowerCase() === r.answer.toLowerCase()) b.classList.add("right"); else if (b.dataset.o === val) b.classList.add("wrong"); });
    const verdict = r.kind === "tf" ? (r.statement_is_true ? "This statement is true: it is in the book." : "This statement is false: the book says otherwise.") : "";
    document.getElementById("tryfb").innerHTML = `<div class="feedback ${r.correct ? "good" : "bad"} anim" style="margin-top:10px"><div class="row" style="flex-wrap:nowrap">${ringSvg(r.mastery.p_known * 100, 56, "knowledge")}<div><strong>${r.correct ? "Correct!" : "Not quite."}</strong>
      ${r.kind === "tf" ? esc(verdict) : r.correct ? "" : `The answer is <strong>${esc(r.answer)}</strong>.`}<div class="small">Knowledge of this topic: ${esc(r.mastery.level)}</div></div></div>
      <div class="quote" style="margin-top:8px">${esc(r.quote)}</div><div class="where">Book line ${r.line} · characters ${r.start}&ndash;${r.end} · <a href="#/topic/${topic.id}?hl=${r.start}-${r.end}">find in text &rarr;</a></div></div>`;
    animateRings(out); fx.answer(r);
  } catch (e) { toast(e.message); }
}
async function wireHero(book) {
  const box = document.getElementById("try"); if (!box) return;
  const ta = document.getElementById("tryq"), out = document.getElementById("tryout"), time = document.getElementById("trytime");
  const ex = tryExamples(book);
  let mode = "ask", detail = null, seq = 0;
  const setMode = (m) => {
    mode = m;
    box.querySelectorAll(".seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === m)));
    document.getElementById("trylabel").textContent = m === "ask" ? "Your question" : "A topic to be quizzed on";
  };
  const run = async (record) => {
    const text = ta.value.trim(); if (!text) return;
    const my = ++seq, rb = document.getElementById("tryrun"); fx.busy(rb, true); out.innerHTML = skeleton(2).replace('<div class="skel h1"></div>', ""); time.innerHTML = "";
    const t0 = performance.now();
    try {
      if (mode === "ask") {
        const r = await api("/ask", { method: "POST", json: { book_id: book.id, question: text, log: record } });
        if (my !== seq) return; const ms = Math.round(performance.now() - t0);
        out.innerHTML = tryAnswer(r); time.innerHTML = `<span class="timing">&#9889; ${ms} ms</span>`;
      } else {
        detail = detail || (await api("/books/" + book.id));
        let topic = pickTopic(detail, text);
        if (!topic) {
          const r = await api("/ask", { method: "POST", json: { book_id: book.id, question: text, log: false } });
          const rel = r.related[0];
          if (rel) topic = (detail.course || []).flatMap((c) => c.topics).find((t) => t.id === rel.topic_id);
        }
        if (!topic) { if (my === seq) out.innerHTML = `<div class="answer-box none anim"><strong>No matching topic.</strong> The book has nothing on that, so there is nothing to quiz.</div>`; return; }
        const qs = (await api(`/topics/${topic.id}/quiz?n=1`)).questions;
        if (my !== seq) return; const ms = Math.round(performance.now() - t0);
        if (!qs.length) { out.innerHTML = `<div class="answer-box none anim">No question could be generated for <strong>${esc(topic.title)}</strong>.</div>`; return; }
        const q = qs[0]; out.innerHTML = tryQuiz(q, topic); time.innerHTML = `<span class="timing">&#9889; ${ms} ms</span>`;
        if (q.kind === "cloze") {
          const inp = document.getElementById("tryresp"), go = () => inp.value.trim() && trySubmit(q, topic, inp.value, out);
          document.getElementById("trycheck").onclick = go; inp.onkeydown = (e) => { if (e.key === "Enter") go(); };
        } else out.querySelectorAll(".opt").forEach((b) => (b.onclick = () => trySubmit(q, topic, b.dataset.o, out)));
      }
    } catch (e) { if (my === seq) out.innerHTML = `<div class="answer-box none">${esc(e.message)}</div>`; }
    finally { fx.busy(rb, false); }
  };
  box.querySelectorAll(".seg button").forEach((b) => (b.onclick = () => {
    if (b.dataset.mode === mode) return; setMode(b.dataset.mode);
    const e = ex.find((x) => x.mode === mode); if (e) ta.value = e.text; run(true);
  }));
  box.querySelectorAll(".chip[data-i]").forEach((c) => (c.onclick = (ev) => {
    ev.preventDefault(); const e = ex[Number(c.dataset.i)]; setMode(e.mode); ta.value = e.text; run(true);
  }));
  document.getElementById("tryrun").onclick = () => run(true);
  ta.onkeydown = (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); run(true); } };
  run(false); // the page-load run is a preview: not written to the question history
}

/* ---------- dashboard ---------- */
route(/^\/$/, "home", async () => {
  const d = await api("/dashboard"); state.llm = d.llm;
  const t = d.totals, a = d.activity;
  const ready = d.books.filter((b) => b.status === "ready");
  const tryBook = ready.find((b) => b.source_type === "sample") || ready[0];
  const tryDetail = tryBook ? await api("/books/" + tryBook.id) : null;
  const hero = heroHtml(tryDetail);
  if (!d.books.length) {
    $app.innerHTML = hero; document.getElementById("sample").onclick = loadSample; return;
  }
  const max = Math.max(1, d.daily_goal, ...a.series.map((s) => s.answered));
  const chart = a.series.map((s) => `<div class="col" title="${s.date}: ${s.answered} answered, ${s.correct} right"><i class="${s.answered ? "" : "zero"}" style="height:${Math.max(2, (s.answered / max) * 88)}%"></i><span>${s.date.slice(8)}</span></div>`).join("");
  const goalBottom = 20 + (d.daily_goal / max) * 0.88 * 82;
  $app.innerHTML = `
    ${hero}
    <div class="row" style="margin-bottom:14px"><h2 style="margin:0;font-size:1.5rem">Your progress</h2><a class="btn right" href="#/library">+ Add a book</a></div>
    <div class="stats">
      <div class="stat ringstat">${ringSvg(t.topics ? (t.mastered / t.topics) * 100 : 0, 64, "topics mastered")}<div><div class="v">${t.mastered}<span class="muted" style="font-size:1rem">/${t.topics}</span></div><div class="l">topics mastered</div></div></div>
      <div class="stat"><div class="v">${t.due}</div><div class="l">reviews due now</div></div>
      <div class="stat"><div class="v">${a.streak}</div><div class="l">day streak</div></div>
      <div class="stat"><div class="v">${a.accuracy == null ? "–" : pct(a.accuracy) + "%"}</div><div class="l">answer accuracy</div></div>
      <div class="stat"><div class="v">${t.questions_asked}</div><div class="l">questions asked</div></div>
    </div>
    <div class="grid cols-2">
      <section class="card"><h2>What to review next</h2>
        ${d.review_next.length ? d.review_next.map((r) => `
          <div class="li"><div class="main"><a href="#/topic/${r.topic_id}?quiz=1"><strong>${esc(r.topic)}</strong></a>
            <div class="small muted">${esc(r.book)} · ${esc(r.chapter)}</div></div>
            ${pillFor(r.level)}<span class="pill ${r.due ? "due" : ""}">${esc(r.reason)}</span></div>`).join("") : `<p class="muted">Nothing yet. Open a topic and take a quiz.</p>`}
        <p style="margin-top:12px"><a href="#/review">Full review schedule →</a></p>
      </section>
      <section class="card"><div class="row"><h2 style="margin:0">Answers, last 14 days</h2><span class="small muted right">goal ${d.daily_goal}/day · today ${a.today}</span></div>
        <div class="chart">${chart}<div class="goal" style="bottom:${goalBottom}%" title="daily goal"></div></div>
        <div class="bar big" style="margin-top:14px" title="today vs goal"><i style="width:${Math.min(100, (a.today / d.daily_goal) * 100)}%"></i></div>
        <p class="small muted">${a.today >= d.daily_goal ? "Daily goal reached." : `${d.daily_goal - a.today} more answers to reach today's goal.`}</p>
      </section>
    </div>
    <h2 style="margin-top:24px">Your books</h2>
    <div class="grid cols-3">${d.books.map(bookCard).join("")}</div>`;
  animateRings($app); if (tryDetail) wireHero(tryDetail);
});
function bookCard(b) {
  if (b.status !== "ready") return `<div class="card book-card"><h3>${esc(b.title)}</h3><p class="${b.status === "error" ? "" : "muted"}">${b.status === "error" ? "Import failed: " + esc(b.error) : '<span class="spinner"></span> Processing…'}</p><button class="btn danger small" data-del="${b.id}">Remove</button></div>`;
  const p = b.progress, share = p.topics ? (p.mastered / p.topics) * 100 : 0;
  return `<div class="card book-card"><div class="row">${ringSvg(share, 68, "topics mastered")}
      <div><h3><a href="#/book/${b.id}">${esc(b.title)}</a></h3><div class="small muted">${b.chapters} chapters · ${p.topics} topics · ${b.n_words.toLocaleString()} words</div></div></div>
    ${bar(p.avg_known)}<div class="small muted">${p.practised}/${p.topics} practised · ${p.mastered} mastered · ${p.due ? `<strong style="color:var(--bad)">${p.due} due</strong>` : "none due"}</div>
    <div class="row"><a class="btn small" href="#/book/${b.id}">Course</a><a class="btn secondary small" href="#/ask/${b.id}">Ask</a></div></div>`;
}
async function loadSample() {
  try { await api("/books/sample", { method: "POST" }); toast("Sample book loaded"); } catch (e) { toast(e.message); }
  render();
}

/* ---------- library ---------- */
route(/^\/library$/, "library", async () => {
  const books = await api("/books");
  $app.innerHTML = `<h1>Library</h1>
    <div class="grid cols-2">
      <section class="card stack"><h2>Add a book</h2>
        <div class="drop" id="drop" tabindex="0" role="button" aria-label="Choose a file"><strong>Drop a PDF, markdown, text or HTML file here</strong><div class="muted small">or click to choose · up to 60 MB · PDFs need a text layer (no OCR)</div>
          <input type="file" id="file" accept=".pdf,.md,.markdown,.txt,.html,.htm" hidden></div>
        <div><label for="url">…or paste a web page address</label><div class="row" style="flex-wrap:nowrap"><input type="url" id="url" placeholder="https://example.org/article"><button class="btn" id="addurl">Add</button></div></div>
        <details><summary class="small">…or paste text</summary><textarea id="pasted" aria-label="Pasted text" placeholder="Paste lecture notes or an article" style="margin-top:6px"></textarea>
          <p><button class="btn secondary small" id="addtext">Add pasted text</button></p></details>
        <div><label for="title">Title (optional)</label><input type="text" id="title" placeholder="Taken from the file when left empty"></div>
        <button class="btn secondary" id="sample">Load the sample book</button>
        <p class="small muted" id="msg"></p>
      </section>
      <section class="card"><h2>Books</h2><div id="books">${booksList(books)}</div></section>
    </div>`;
  const drop = document.getElementById("drop"), file = document.getElementById("file");
  drop.onclick = () => file.click();
  drop.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") file.click(); };
  ["dragover", "dragenter"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => { if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); });
  file.onchange = () => file.files[0] && upload(file.files[0]);
  document.getElementById("addurl").onclick = () => { const u = document.getElementById("url").value.trim(); if (u) upload(null, u); };
  document.getElementById("sample").onclick = async () => { await loadSample(); };
  document.getElementById("addtext").onclick = () => { const t = document.getElementById("pasted").value; if (t.trim()) upload(null, null, t); };
  wireDelete(); pollBooks(books);
});
function booksList(books) {
  if (!books.length) return `<p class="muted">No books yet.</p>`;
  return books.map((b) => `<div class="li"><div class="main"><strong>${b.status === "ready" ? `<a href="#/book/${b.id}">${esc(b.title)}</a>` : esc(b.title)}</strong>
    <div class="small muted">${b.status === "ready" ? `${b.chapters} chapters · ${b.n_words.toLocaleString()} words · ${esc(b.source_type)}` : b.status === "error" ? "Failed: " + esc(b.error) : '<span class="spinner"></span> converting…'}</div></div>
    <button class="btn danger small" data-del="${b.id}">Delete</button></div>`).join("");
}
function wireDelete() {
  document.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    if (!confirm("Delete this book and all its progress, notes and history?")) return;
    await api("/books/" + b.dataset.del, { method: "DELETE" }); toast("Deleted"); render();
  }));
}
function pollBooks(books) {
  if (!books.some((b) => b.status === "processing")) return;
  state.polling = setTimeout(async () => {
    if (!location.hash.startsWith("#/library")) return;
    const fresh = await api("/books"); const el = document.getElementById("books");
    if (el) { el.innerHTML = booksList(fresh); wireDelete(); }
    pollBooks(fresh);
  }, 1500);
}
async function upload(file, url, text) {
  const msg = document.getElementById("msg"); msg.innerHTML = `<span class="spinner"></span> Uploading…`;
  const btn = document.getElementById(url ? "addurl" : text ? "addtext" : "drop") || msg;
  const form = new FormData(); const title = document.getElementById("title").value.trim();
  if (file) form.append("file", file); if (url) form.append("url", url); if (text) form.append("text", text); if (title) form.append("title", title);
  try { await api("/books", { method: "POST", form }); msg.textContent = "Converting in the background…"; toast("Import started"); fx.flash(btn, true); render(); }
  catch (e) { msg.textContent = "Could not add: " + e.message; fx.flash(btn, false); }
}

/* ---------- book / course outline ---------- */
route(/^\/book\/(\d+)$/, "library", async (m) => {
  const b = await api("/books/" + m[1]);
  if (b.status !== "ready") { $app.innerHTML = `<div class="card"><h2>${esc(b.title)}</h2><p>${b.status === "error" ? "Import failed: " + esc(b.error) : "Still processing…"}</p></div>`; return; }
  const p = b.progress;
  $app.innerHTML = `
    <div class="row" style="margin-bottom:6px"><a href="#/">← Dashboard</a></div>
    <div class="row"><h1 style="margin:0">${esc(b.title)}</h1><a class="btn right" href="#/ask/${b.id}">Ask this book</a>
      <a class="btn secondary" href="/api/books/${b.id}/notes.md" download>Export my notes</a>
      <a class="btn secondary" href="/api/books/${b.id}/flashcards.csv" download title="One card per concept the book defines; imports into Anki">Flashcards (CSV)</a>
      <a class="btn secondary" href="/api/books/${b.id}/markdown" target="_blank" rel="noopener">Book text</a></div>
    <p class="muted">${b.chapters} chapters · ${p.topics} topics · ${b.n_words.toLocaleString()} words · ${esc(b.source_type)}${b.meta.author ? " · " + esc(b.meta.author) : ""}${b.meta.licence ? " · " + esc(b.meta.licence) : ""}</p>
    <div class="stats"><div class="stat"><div class="v">${p.mastered}/${p.topics}</div><div class="l">mastered</div></div>
      <div class="stat"><div class="v">${p.practised}</div><div class="l">practised</div></div>
      <div class="stat"><div class="v">${p.due}</div><div class="l">due for review</div></div>
      <div class="stat"><div class="v">${pct(p.avg_known)}%</div><div class="l">average knowledge</div></div></div>
    <div class="outline">${b.course.map((c, ci) => `<details class="chapter" ${ci < 2 || c.topics.some((t) => t.mastery.due) ? "open" : ""}>
      <summary>${esc(c.title)}<span class="small muted right">${c.topics.length} topic${c.topics.length === 1 ? "" : "s"}</span></summary>
      <div class="card flat" style="margin-top:6px;padding:4px 8px">${c.topics.map(topicRow).join("")}</div></details>`).join("")}</div>`;
});
function topicRow(t) {
  const m = t.mastery;
  return `<div class="topic-row"><div><a class="t" href="#/topic/${t.id}">${esc(t.title)}</a> ${m.due ? '<span class="pill due">due</span>' : ""}
      ${t.summary ? `<div class="sum">${esc(t.summary.length > 180 ? t.summary.slice(0, 177) + "…" : t.summary)}</div>` : ""}
      <div>${t.concepts.slice(0, 6).map((c) => `<span class="chip static" title="${c.definition ? esc(c.definition) : ""}">${esc(c.term)}</span>`).join("")}</div></div>
    <div>${pillFor(m.level)} <span class="small muted">${t.n_words} words</span>${bar(m.attempts ? m.p_known : 0)}
      <div class="small muted">${m.attempts ? `knows ${pct(m.p_known)}% · ${m.correct}/${m.attempts} right` : "not started"}</div>
      <a class="btn small" style="margin-top:6px" href="#/topic/${t.id}?quiz=1">Quiz</a></div></div>`;
}

/* ---------- topic: read + quiz ---------- */
route(/^\/topic\/(\d+)$/, "library", async (m, params) => {
  const t = await api("/topics/" + m[1]);
  const hl = params.get("hl") ? params.get("hl").split("-").map((x) => Number(x) - t.start) : null;
  api("/events", { method: "POST", json: { kind: "read", topic_id: t.id } }).catch(() => {});
  $app.innerHTML = `
    <div class="row" style="margin-bottom:6px"><a href="#/book/${t.book_id}">← ${esc(t.book)}</a><span class="muted">/ ${esc(t.chapter)}</span></div>
    <div class="layout"><div>
      <h1>${esc(t.title)}</h1>
      <div class="row small muted" style="margin-bottom:10px">${pillFor(t.mastery.level)} <span>${t.n_words} words</span>
        ${t.prev ? `<a href="#/topic/${t.prev.id}">← ${esc(t.prev.title)}</a>` : ""}${t.next ? `<a class="right" href="#/topic/${t.next.id}">${esc(t.next.title)} →</a>` : ""}</div>
      ${t.summary ? `<div class="card flat" style="margin-bottom:14px"><strong>In short.</strong> ${esc(t.summary)}</div>` : ""}
      <div class="card flat" style="margin-bottom:14px"><strong>Key concepts</strong><div style="margin-top:6px">${t.concepts.map((c) => `<a class="chip" href="#/ask/${t.book_id}?q=${encodeURIComponent("What does the book say about " + c.term + "?")}" title="${c.definition ? esc(c.definition) : "ask about " + esc(c.term)}">${esc(c.term)}</a>`).join("") || '<span class="muted">none found</span>'}</div></div>
      <article class="card reading" id="reading">${renderMd(t.text, hl)}</article>
      <section class="card" style="margin-top:16px"><h2>Your notes</h2>
        <div id="notes">${t.notes.map(noteHtml).join("")}</div>
        <textarea id="newnote" placeholder="Write a note about this topic…" aria-label="New note"></textarea>
        <p><button class="btn secondary" id="addnote">Save note</button></p></section>
    </div>
    <aside class="sticky"><div class="card" id="quizbox"></div></aside></div>`;
  const hlEl = document.querySelector("mark.hl"); if (hlEl) hlEl.scrollIntoView({ block: "center", behavior: "smooth" });
  document.getElementById("addnote").onclick = async () => {
    const ta = document.getElementById("newnote"); if (!ta.value.trim()) return;
    const n = await api("/notes", { method: "POST", json: { topic_id: t.id, text: ta.value } });
    document.getElementById("notes").insertAdjacentHTML("afterbegin", noteHtml(n)); ta.value = ""; wireNotes(); toast("Note saved");
  };
  wireNotes(); quizIntro(t); if (params.get("quiz")) startQuiz(t);
});
function noteHtml(n) {
  return `<div class="cite" data-note="${n.id}"><div class="note-text">${esc(n.text).replace(/\n/g, "<br>")}</div>
    <div class="where">${dt(n.updated)} · <a href="#" data-edit="${n.id}">edit</a> · <a href="#" data-rm="${n.id}">delete</a></div></div>`;
}
function wireNotes() {
  document.querySelectorAll("[data-rm]").forEach((a) => (a.onclick = async (e) => { e.preventDefault(); await api("/notes/" + a.dataset.rm, { method: "DELETE" }); a.closest("[data-note]").remove(); toast("Note deleted"); }));
  document.querySelectorAll("[data-edit]").forEach((a) => (a.onclick = async (e) => {
    e.preventDefault(); const box = a.closest("[data-note]"), cur = box.querySelector(".note-text").innerText;
    const next = prompt("Edit note", cur); if (next && next.trim()) { const n = await api("/notes/" + a.dataset.edit, { method: "PUT", json: { text: next } }); box.outerHTML = noteHtml(n); wireNotes(); }
  }));
}
function quizIntro(t) {
  const m = t.mastery;
  document.getElementById("quizbox").innerHTML = `<h2>Quiz this topic</h2>
    <p class="muted small">${t.n_questions} questions from the text: fill-in-the-blank, multiple choice and true/false. Answers are graded here and update your knowledge estimate.</p>
    <div class="row small">${pillFor(m.level)}<span class="muted">${m.attempts ? `knows ${pct(m.p_known)}% · recall now ${pct(m.recall)}%` : "not started"}</span></div>
    ${bar(m.attempts ? m.p_known : 0, true)}
    <p class="small muted">${m.due_in_days == null ? "" : "Next review " + when(m.due_in_days)}</p>
    <p><button class="btn" id="startq">${m.attempts ? "Practise again" : "Start quiz"}</button>
    ${state.llm?.configured ? `<button class="btn secondary" id="genq" title="Ask the configured model for extra questions; each is kept only if its quote is in the text">+ Model questions</button>` : ""}</p>`;
  document.getElementById("startq").onclick = () => startQuiz(t);
  const g = document.getElementById("genq");
  if (g) g.onclick = async () => { g.disabled = true; try { const r = await api(`/topics/${t.id}/quiz/generate`, { method: "POST" }); toast(`${r.added} added, ${r.rejected} rejected${r.error ? " (" + r.error + ")" : ""}`); } catch (e) { toast(e.message); } g.disabled = false; };
  if (!state.llm) api("/llm").then((l) => { state.llm = l; if (l.configured) quizIntro(t); }).catch(() => {});
}
async function startQuiz(t) {
  const r = await api(`/topics/${t.id}/quiz?n=6`);
  state.quiz = { topic: t, qs: r.questions, i: 0, right: 0, done: 0 };
  showQuestion();
}
function showQuestion() {
  const z = state.quiz, box = document.getElementById("quizbox");
  if (!z) return;
  if (z.i >= z.qs.length) return quizDone();
  const q = z.qs[z.i];
  const kinds = { cloze: "Fill in the blank", mcq: "Choose the missing word", tf: "True or false?" };
  const prompt = esc(q.prompt).replace("_____", '<span class="blank">&nbsp;&nbsp;&nbsp;&nbsp;</span>');
  let inputs;
  if (q.kind === "cloze") inputs = `<input type="text" id="resp" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Type the missing word  (${esc(q.hint || "")})" aria-label="answer"><p><button class="btn" id="submit">Check</button></p>`;
  else inputs = (q.options).map((o, k) => `<button class="opt" data-o="${esc(o)}"><kbd>${k + 1}</kbd>${esc(o[0].toUpperCase() + o.slice(1))}</button>`).join("");
  box.innerHTML = `<div class="row small muted"><span>Question ${z.i + 1} of ${z.qs.length}</span><span class="right">${esc(kinds[q.kind])}</span></div>
    <div class="bar" style="margin:6px 0"><i style="width:${(z.i / z.qs.length) * 100}%"></i></div>
    <div class="q-prompt">${prompt}</div><div id="inputs">${inputs}</div><div id="fb"></div>`;
  const send = (val) => submitAnswer(q, val);
  if (q.kind === "cloze") {
    const inp = document.getElementById("resp"); inp.focus();
    const go = () => inp.value.trim() && send(inp.value);
    document.getElementById("submit").onclick = go; inp.onkeydown = (e) => { if (e.key === "Enter") go(); };
  } else document.querySelectorAll(".opt").forEach((b) => (b.onclick = () => send(b.dataset.o)));
}
async function submitAnswer(q, val) {
  const z = state.quiz; if (!z || z.busy) return; z.busy = true;
  document.querySelectorAll("#inputs button, #inputs input").forEach((e) => (e.disabled = true));
  try {
    const r = await api("/quiz/answer", { method: "POST", json: { question_id: q.id, response: val } });
    z.done++; if (r.correct) z.right++; z.last = r; fx.answer(r);
    fx.flash(document.getElementById("submit") || document.querySelector(".opt.right, .opt[data-o]"), true);
    document.querySelectorAll(".opt").forEach((b) => { if (b.dataset.o.toLowerCase() === r.answer.toLowerCase()) b.classList.add("right"); else if (b.dataset.o === val) b.classList.add("wrong"); });
    const verdict = r.kind === "tf" ? (r.statement_is_true ? "This statement is true: it is in the book." : "This statement is false: the book says otherwise.") : "";
    document.getElementById("fb").innerHTML = `<div class="feedback ${r.correct ? "good" : "bad"}"><strong>${r.correct ? "Correct." : "Not quite."}</strong>
      ${r.kind === "tf" ? esc(verdict) : r.correct ? "" : `The answer is <strong>${esc(r.answer)}</strong>.`}
      <div class="quote">${esc(r.quote)}</div><div class="small muted">Book line ${r.line} · <a href="#/topic/${q.topic_id}?hl=${r.start}-${r.end}">find in text</a></div>
      <div class="small">Knowledge now ${pct(r.mastery.p_known)}% (${esc(r.mastery.level)})</div>${bar(r.mastery.p_known)}</div>
      <p><button class="btn" id="next">${z.i + 1 >= z.qs.length ? "Finish" : "Next"} →</button></p>`;
    const nx = document.getElementById("next"); nx.focus();
    nx.onclick = () => { z.i++; z.busy = false; showQuestion(); };
  } catch (e) { z.busy = false; toast(e.message); fx.flash(document.getElementById("submit") || document.querySelector(".opt"), false); }
}
async function quizDone() {
  const z = state.quiz, box = document.getElementById("quizbox"), last = z.last.mastery;
  const nxt = await api(`/review/next?book_id=${z.topic.book_id}&limit=3`).catch(() => []);
  box.innerHTML = `<h2>Done: ${z.right}/${z.done} right</h2>
    <p>Knowledge of this topic: <strong>${pct(last.p_known)}%</strong> ${pillFor(last.level)}</p>${bar(last.p_known, true)}
    <p class="small muted">Next review ${when(last.due_in_days)}.</p>
    <p><button class="btn" id="again">Another round</button> ${z.topic.next ? `<a class="btn secondary" href="#/topic/${z.topic.next.id}?quiz=1">Next topic</a>` : ""}</p>
    ${nxt.length ? `<h3>Review next</h3>${nxt.map((r) => `<div class="li"><div class="main"><a href="#/topic/${r.topic_id}?quiz=1">${esc(r.topic)}</a><div class="small muted">${esc(r.reason)}</div></div></div>`).join("")}` : ""}`;
  document.getElementById("again").onclick = () => startQuiz(z.topic);
  if (z.right === z.done && z.done > 0) fx.burstAt(box.querySelector("h2"), 60, 1.6);
}
document.addEventListener("keydown", (e) => {
  const z = state.quiz; if (!z || e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
  if (/^[1-4]$/.test(e.key)) { const b = document.querySelectorAll(".opt:not(:disabled)")[Number(e.key) - 1]; if (b) b.click(); }
  if (e.key === "Enter") { const n = document.getElementById("next"); if (n) n.click(); }
});

/* ---------- ask the book ---------- */
route(/^\/ask(?:\/(\d+))?$/, "ask", async (m, params) => {
  const books = (await api("/books")).filter((b) => b.status === "ready");
  if (!books.length) { $app.innerHTML = `<div class="card empty"><h2>No books yet</h2><a class="btn" href="#/library">Add a book</a></div>`; return; }
  const bookId = Number(m[1] || state.ask.bookId || books[0].id); state.ask.bookId = bookId;
  const book = await api("/books/" + bookId);
  const hist = await api("/history?book_id=" + bookId + "&limit=8");
  $app.innerHTML = `<h1>Ask the book</h1>
    <div class="card stack"><div class="row"><label for="bk" style="margin:0">Book</label>
      <select id="bk" style="width:auto;max-width:100%">${books.map((b) => `<option value="${b.id}" ${b.id === bookId ? "selected" : ""}>${esc(b.title)}</option>`).join("")}</select>
      <span class="small muted right">Answers use only this book. Urdu, Roman Urdu and English questions work.</span></div>
      <form class="ask-input" id="askf"><input type="text" id="q" dir="auto" placeholder="e.g. What is hydrogen?   ·   موم بتی کیوں جلتی ہے؟   ·   pani kaise banta hai" aria-label="Your question" autofocus><button class="btn" id="go">Ask</button></form>
      <div>${(book.suggestions || []).map((s) => `<a class="chip" data-q="${esc(s)}">${esc(s)}</a>`).join("")}
        ${["موم بتی کیوں جلتی ہے؟", "pani kaise banta hai", "ہائیڈروجن کیا ہے؟"].map((s) => `<a class="chip" data-q="${esc(s)}" dir="auto">${esc(s)}</a>`).join("")}</div></div>
    <div id="result" style="margin-top:16px"></div>
    <h2 style="margin-top:24px">Recent questions in this book</h2>
    <div class="card flat" id="hist">${histHtml(hist)}</div>`;
  document.getElementById("bk").onchange = (e) => (location.hash = "#/ask/" + e.target.value);
  const input = document.getElementById("q");
  const run = async (text) => {
    if (!text.trim()) return; input.value = text;
    const res = document.getElementById("result"), gb = document.getElementById("go"); res.innerHTML = `<p class="muted"><span class="spinner"></span> Searching the book…</p>`; fx.busy(gb, true);
    try { const r = await api("/ask", { method: "POST", json: { book_id: bookId, question: text } }); res.innerHTML = answerHtml(r); fx.flash(gb, true);
      document.getElementById("hist").innerHTML = histHtml(await api("/history?book_id=" + bookId + "&limit=8")); }
    catch (e) { res.innerHTML = `<div class="card">${esc(e.message)}</div>`; fx.shake(res); fx.flash(gb, false); }
    finally { fx.busy(gb, false); }
  };
  document.getElementById("askf").onsubmit = (e) => { e.preventDefault(); run(input.value); };
  document.querySelectorAll("[data-q]").forEach((c) => (c.onclick = () => run(c.dataset.q)));
  if (params.get("q")) run(params.get("q"));
});
const LANG = { en: "English", ur: "Urdu", "roman-ur": "Roman Urdu", mixed: "mixed Urdu/English" };
function answerHtml(r) {
  const a = r.analysis;
  const understood = `<div class="small muted" style="margin-bottom:8px">Read as <strong>${LANG[a.language] || a.language}</strong>${a.intent ? " · asking <em>" + esc(a.intent) + "</em>" : ""} · searched for: ${a.terms.map((t) => `<span class="chip static">${esc(t)}</span>`).join("") || "nothing"}
    ${a.mapped.filter((x) => x.how !== "english word").length ? `<div>${a.mapped.map((x) => `<span class="small" ${isRTL(x.from) ? 'dir="rtl"' : ""}>${esc(x.from)}</span> → <span class="small">${esc(x.to)}</span> <span class="muted small">(${esc(x.how)})</span>`).join(" · ")}</div>` : ""}
    ${a.ignored.length ? `<div>not understood: ${a.ignored.map(esc).join(", ")}</div>` : ""}</div>`;
  if (!r.answered) return `${understood}<div class="answer-box none"><strong>The book does not say.</strong> ${esc(r.message.replace(/^The book does not say\.\s*/, "") || "No passage covers that question.")}
      ${r.related.length ? `<div class="small" style="margin-top:8px">Closest topics: ${r.related.map((x) => `<a href="#/topic/${x.topic_id}">${esc(x.topic)}</a>`).join(", ")}</div>` : ""}</div>`;
  const mode = r.mode.startsWith("llm") ? `written by ${esc(r.mode.slice(4))}, every quote checked against the book` : "extractive: the book's own sentences";
  return `${understood}<div class="answer-box"><div class="small muted" style="margin-bottom:6px">${mode}${r.dropped_quotes ? ` · ${r.dropped_quotes} unverifiable quote(s) dropped` : ""}</div>
    ${r.mode.startsWith("llm") ? esc(r.answer) : r.citations.map((c) => `${esc(c.quote)} <sup>[${c.n}]</sup>`).join(" ")}</div>
    <h3 style="margin-top:14px">Sources</h3>${r.citations.map((c) => `<div class="cite"><div class="quote" style="margin:0">${esc(c.quote)}</div>
      <div class="where"><strong>[${c.n}]</strong> ${esc(c.chapter || "")} › ${esc(c.topic || "")} · line ${c.line} · characters ${c.start}–${c.end} · <span title="the quote was found at exactly these offsets in the book">verified</span>
        · <a href="#/topic/${c.topic_id}?hl=${c.start}-${c.end}">open in the book →</a></div></div>`).join("")}
    ${r.related.length ? `<div class="small muted">Related topics: ${r.related.map((x) => `<a href="#/topic/${x.topic_id}?quiz=1">${esc(x.topic)}</a>`).join(", ")}</div>` : ""}`;
}
function histHtml(h) {
  if (!h.length) return `<p class="muted">No questions yet.</p>`;
  return h.map((x) => `<div class="li"><div class="main" ${isRTL(x.question) ? 'dir="rtl"' : ""}>${esc(x.question)}</div><span class="pill">${esc(x.language || "")}</span><span class="pill ${x.answered ? "mastered" : "learning"}">${x.answered ? "answered" : "not in book"}</span><span class="small muted">${dt(x.ts)}</span></div>`).join("");
}

/* ---------- review ---------- */
route(/^\/review$/, "review", async () => {
  const [next, sch] = await Promise.all([api("/review/next?limit=12"), api("/review/schedule")]);
  const group = (title, rows) => rows.length ? `<h3>${title}</h3>${rows.map((r) => `<div class="li"><div class="main"><a href="#/topic/${r.topic_id}?quiz=1"><strong>${esc(r.topic)}</strong></a><div class="small muted">${esc(r.book)} · ${esc(r.chapter)}</div></div>
      ${pillFor(r.level)}<span class="small muted" style="min-width:90px;text-align:right">${when(r.due_in_days)}</span><div style="width:90px">${bar(r.recall)}</div></div>`).join("")}` : "";
  const any = sch.overdue.length + sch.today.length + sch.this_week.length + sch.later.length;
  $app.innerHTML = `<h1>Review</h1><div class="grid cols-2">
    <section class="card"><h2>What to review next</h2>${next.length ? next.map((r) => `<div class="li"><div class="main"><a href="#/topic/${r.topic_id}?quiz=1"><strong>${esc(r.topic)}</strong></a>
      <div class="small muted">${esc(r.book)} · ${esc(r.reason)}</div></div>${pillFor(r.level)}<a class="btn small" href="#/topic/${r.topic_id}?quiz=1">Quiz</a></div>`).join("") : `<p class="muted">Nothing to review yet.</p>`}
      <p class="small muted">Order: topics that are due (weakest and latest first), then the next unstarted topic of each book, then shaky ones. Knowledge is the BKT estimate P(known); the bar shows what you are still expected to remember today.</p></section>
    <section class="card sched"><h2>Spaced-review schedule</h2>${any ? group("Overdue", sch.overdue) + group("Today", sch.today) + group("This week", sch.this_week) + group("Later", sch.later) : `<p class="muted">Take a quiz and your topics will appear here with their next review date.</p>`}</section></div>`;
});

/* ---------- memory & settings ---------- */
route(/^\/memory$/, "memory", async () => {
  const [notes, hist, sess, settings, llm] = await Promise.all([api("/notes"), api("/history?limit=30"), api("/memory/sessions"), api("/settings"), api("/llm")]);
  $app.innerHTML = `<h1>Memory</h1>
    <div class="card" style="margin-bottom:16px"><div class="row"><input type="text" id="mq" placeholder="Search your notes and past questions…" aria-label="Search memory" style="flex:1"><button class="btn" id="msearch">Search</button></div><div id="mres"></div></div>
    <div class="grid cols-2"><section class="card"><h2>Notes (${notes.length})</h2>${notes.length ? notes.map((n) => `<div class="cite"><div>${esc(n.text).replace(/\n/g, "<br>")}</div><div class="where">${esc(n.book || "")} › <a href="#/topic/${n.topic_id}">${esc(n.topic || "book")}</a> · ${dt(n.updated)}</div></div>`).join("") : '<p class="muted">Notes you write on a topic page show up here.</p>'}</section>
    <section class="card"><h2>Question history</h2>${histHtml(hist)}</section>
    <section class="card"><h2>Sessions</h2>${sess.map((s) => `<div class="li"><div class="main">${dt(s.started)}</div><span class="small muted">${s.questions} questions · ${s.answers} quiz answers</span></div>`).join("") || '<p class="muted">None yet.</p>'}</section>
    <section class="card stack"><h2>Settings</h2>
      <div><label for="goal">Daily goal (answers per day)</label><input type="number" id="goal" min="1" max="500" value="${settings.daily_goal}"></div>
      <div class="switch"><input type="checkbox" id="usellm" ${settings.use_llm ? "checked" : ""}><label for="usellm" style="margin:0">Use the language model for answers when one is configured</label></div>
      <p class="small muted">Model: ${llm.configured ? `<strong>${esc(llm.provider)}</strong> (${esc(llm.model)})` : "none configured. Everything works without one. Set STUDYLOOP_LLM=ollama (or anthropic / openai) before launching to enable it."}${llm.note ? " " + esc(llm.note) : ""}</p>
      <button class="btn" id="save">Save settings</button></section></div>`;
  const doSearch = async () => {
    const q = document.getElementById("mq").value.trim(); if (!q) return;
    const r = await api("/memory/search?q=" + encodeURIComponent(q));
    document.getElementById("mres").innerHTML = r.length ? r.map((x) => `<div class="cite"><span class="pill">${x.type}</span> ${esc(x.type === "question" ? x.question : x.text)}<div class="where">${esc(x.book || "")} · ${dt(x.ts)} · score ${x.score}</div></div>`).join("") : '<p class="muted">Nothing matches.</p>';
  };
  document.getElementById("msearch").onclick = doSearch; document.getElementById("mq").onkeydown = (e) => e.key === "Enter" && doSearch();
  document.getElementById("save").onclick = async () => {
    await api("/settings", { method: "PUT", json: { daily_goal: Number(document.getElementById("goal").value) || 10, use_llm: document.getElementById("usellm").checked } }); toast("Settings saved");
  };
});

/* ---------- boot ---------- */
(async () => {
  try { const s = await api("/settings"); state.settings = s; if (s.theme !== "auto") applyTheme(s.theme); } catch (e) { /* first paint without settings */ }
  render();
})();
