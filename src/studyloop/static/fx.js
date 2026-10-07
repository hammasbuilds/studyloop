"use strict";
/* StudyLoop micro-interactions. Vanilla, no dependencies. Respects prefers-reduced-motion. */
const fx = (() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)");
  const fine = matchMedia("(hover: hover) and (pointer: fine)");
  const COLORS = ["#7d59f7", "#ff6a55", "#ffb627", "#5ee090", "#b3a5ff"];

  function burst(x, y, n = 14, spread = 1) {
    if (reduce.matches) return;
    for (let i = 0; i < n; i++) {
      const p = document.createElement("i"); p.className = "confetti";
      p.style.cssText = `left:${x}px;top:${y}px;background:${COLORS[i % COLORS.length]};`;
      document.body.appendChild(p);
      const a = Math.random() * Math.PI * 2, d = (60 + Math.random() * 120) * spread;
      const dx = Math.cos(a) * d, dy = Math.sin(a) * d - 60 * spread;
      const anim = p.animate([
        { transform: "translate(-50%,-50%) scale(.4) rotate(0)", opacity: 1 },
        { transform: `translate(${dx}px,${dy}px) rotate(${Math.random() * 540}deg)`, opacity: 1, offset: 0.55 },
        { transform: `translate(${dx * 1.15}px,${dy + 140}px) rotate(${Math.random() * 720}deg)`, opacity: 0 },
      ], { duration: 900 + Math.random() * 500, easing: "cubic-bezier(.2,.6,.3,1)" });
      anim.onfinish = () => p.remove();
    }
  }
  function burstAt(el, n, spread) {
    const r = (el || document.body).getBoundingClientRect();
    burst(r.left + r.width / 2, r.top + Math.min(r.height / 2, 40), n, spread);
  }
  function shake(el) {
    if (!el) return; el.classList.remove("shake"); void el.offsetWidth; el.classList.add("shake");
  }
  /* answer feedback: small burst when right (big at mastery), shake when wrong */
  function answer(r) {
    requestAnimationFrame(() => {
      const fb = document.querySelector("#fb .feedback, #tryfb .feedback");
      if (r.correct) {
        const big = r.mastery && r.mastery.level === "mastered";
        burstAt(fb, big ? 50 : 14, big ? 1.5 : 1);
        if (fb) fb.classList.add("pop");
      } else { shake(fb); const w = document.querySelector(".opt.wrong"); if (w) shake(w); }
    });
  }
  function busy(btn, on) {
    if (!btn) return; btn.classList.toggle("loading", on); btn.disabled = on; btn.setAttribute("aria-busy", String(on));
  }
  function flash(btn, ok) {
    if (!btn) return; const c = ok ? "ok" : "err"; btn.classList.add(c); setTimeout(() => btn.classList.remove(c), 900);
  }

  /* ripple from the pointer on buttons, options, chips */
  document.addEventListener("pointerdown", (e) => {
    const b = e.target.closest(".btn, .opt, .chip, .seg button"); if (!b || b.disabled || reduce.matches) return;
    const r = b.getBoundingClientRect(), s = Math.max(r.width, r.height) * 2;
    const rip = document.createElement("span"); rip.className = "ripple";
    rip.style.cssText = `width:${s}px;height:${s}px;left:${e.clientX - r.left - s / 2}px;top:${e.clientY - r.top - s / 2}px`;
    b.appendChild(rip); rip.addEventListener("animationend", () => rip.remove());
    if (b.classList.contains("chip")) { b.classList.remove("popc"); void b.offsetWidth; b.classList.add("popc"); }
  }, { passive: true });

  /* card spotlight + tilt (fine pointers only) */
  document.addEventListener("pointermove", (e) => {
    if (!fine.matches || reduce.matches || e.pointerType !== "mouse") return;
    const c = e.target.closest(".card:not(.flat), .stat"); if (!c) return;
    const r = c.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    c.style.setProperty("--mx", x + "px"); c.style.setProperty("--my", y + "px");
    if (c.classList.contains("stat") || c.classList.contains("book-card")) {
      c.style.setProperty("--rx", ((y / r.height - 0.5) * -6).toFixed(2) + "deg");
      c.style.setProperty("--ry", ((x / r.width - 0.5) * 6).toFixed(2) + "deg");
    }
  }, { passive: true });
  document.addEventListener("pointerout", (e) => {
    const c = e.target.closest && e.target.closest(".stat, .book-card");
    if (c && !c.contains(e.relatedTarget)) { c.style.removeProperty("--rx"); c.style.removeProperty("--ry"); }
  });

  /* typing feedback: a check mark once a text input holds something */
  document.addEventListener("input", (e) => {
    const t = e.target; if (t.matches && t.matches("input[type=text]")) t.classList.toggle("has-val", t.value.trim().length > 0);
  });

  /* count-up for KPI numbers, bars grow from zero */
  function countUp(el) {
    const n = el.firstChild; if (reduce.matches || !n || n.nodeType !== 3 || !/^\d+$/.test(n.nodeValue.trim())) return;
    const end = +n.nodeValue.trim(); if (end < 2) return;
    const t0 = performance.now(), dur = 700; n.nodeValue = "0";
    const tick = (t) => {
      const k = Math.min(1, (t - t0) / dur);
      n.nodeValue = String(Math.round(end * (1 - Math.pow(1 - k, 3))));
      if (k < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
  function growBar(i) {
    if (reduce.matches || i.dataset.g) return; i.dataset.g = "1";
    const w = i.style.width; if (!w) return; i.style.width = "0%";
    requestAnimationFrame(() => requestAnimationFrame(() => { i.style.width = w; }));
  }
  function enhance(root) {
    root.querySelectorAll(".stat .v").forEach((v) => { if (!v.dataset.c) { v.dataset.c = "1"; countUp(v); } });
    root.querySelectorAll(".bar > i").forEach(growBar);
  }
  const app = document.getElementById("app");
  if (app) {
    let queued = false;
    new MutationObserver(() => {
      if (queued) return; queued = true;
      requestAnimationFrame(() => { queued = false; enhance(app); });
    }).observe(app, { childList: true, subtree: true });
  }
  return { burst, burstAt, shake, answer, busy, flash };
})();
