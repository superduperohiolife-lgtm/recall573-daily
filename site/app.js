/* 573 Recall Reports + ODI 調査（PE / EA を1タブに統合）— タブ一覧・明細・単語タップ和訳 */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const view = $("#view");
  let DATA = null;
  let DICT = {};

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtShort = (iso) => (iso ? new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "—");
  const fmtDate = (iso) => {
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  };

  // 英検2級（CEFR B1）以上の語だけをタップ可能にする
  const WORD = /([A-Za-z][A-Za-z'’-]*[A-Za-z]|[A-Za-z])/g;
  function tap(text) {
    const s = String(text ?? "");
    let out = "", last = 0, m;
    WORD.lastIndex = 0;
    while ((m = WORD.exec(s))) {
      out += esc(s.slice(last, m.index));
      const w = m[0];
      const k = w.toLowerCase().replace(/’/g, "'");
      const isAbbr = w.length > 1 && w === w.toUpperCase();
      if (!isAbbr && DICT[k]) out += `<span class="w" data-k="${esc(k)}">${esc(w)}</span>`;
      else out += esc(w);
      last = m.index + w.length;
    }
    return out + esc(s.slice(last));
  }

  // ------------------------------------------------------------ data
  let INV = { meta: {}, items: [] };
  const upd = (m) => (m && m.generated_at ? `Updated ${m.generated_at.slice(0, 16).replace("T", " ")} JST` : "");
  const days = (m) => (m && m.window_from ? Math.round((new Date(m.window_to) - new Date(m.window_from)) / 864e5) : 30);

  async function load() {
    const opt = { cache: "no-cache" };
    const [a, b, c] = await Promise.all([
      fetch("data/items.json", opt),
      fetch("data/dict.json", opt),
      fetch("data/inv.json", opt).catch(() => null),
    ]);
    DATA = await a.json();
    DICT = await b.json();
    try {
      if (c && c.ok) INV = await c.json();
      else INV = { meta: { error: "Investigation data is not available yet. It appears after the next daily update." }, items: [] };
    } catch (e) {
      INV = { meta: { error: "Could not read investigation data." }, items: [] };
    }
    $("#cnt-recall").textContent = DATA.items.length;
    $("#cnt-inv").textContent = INV.items.length;
    refreshNew();
  }

  // ------------------------------------------------------------ NEW（最新の更新で初めて載ったもの。既読でも消さず、次の更新日まで表示）
  // added / generated_at は JST の ISO 文字列（例 2026-11-27T03:20+09:00）。先頭10文字が JST の日付
  const jstDay = (iso) => (iso || "").slice(0, 10);
  const isNew = (it, meta) => !!(it && it.added && meta && meta.generated_at && jstDay(it.added) === jstDay(meta.generated_at));
  const newDate = (it) => fmtShort(jstDay(it.added));
  const newOf = (tab) => (tab === "recall" ? DATA.items.filter((x) => isNew(x, DATA.meta)) : (INV.items || []).filter((x) => isNew(x, INV.meta)));
  function refreshNew() {
    for (const t of ["recall", "inv"]) {
      const n = newOf(t).length, el = $("#new-" + t);
      el.textContent = n ? `NEW ${n}` : "";
      el.hidden = !n;
    }
  }
  const newBadge = (it, meta) => (isNew(it, meta) ? '<span class="badge-new">NEW</span>' : "");
  const newBar = (tab) => {
    const its = newOf(tab);
    return its.length ? `<div class="newbar"><span><span class="badge-new">NEW · ${esc(newDate(its[0]))}</span> ${its.length} new in this update. Shown until the next update.</span></div>` : "";
  };

  // ------------------------------------------------------------ tabs
  const TABS = {
    recall: { title: "573 Recall Reports" },
    inv: { title: "ODI Investigations (PE / EA / RQ)" },
  };
  function setChrome(tab) {
    $("#tabs").hidden = !tab;
    document.querySelectorAll("#tabs a").forEach((a) => {
      const on = a.dataset.tab === tab;
      a.classList.toggle("on", on);
      a.setAttribute("aria-selected", on ? "true" : "false");
    });
    $("#back").hidden = !!tab;
    if (tab) {
      sessionStorage.setItem("tab", tab);
      document.title = TABS[tab].title;
      $("#title").textContent = TABS[tab].title;
    }
  }

  // ------------------------------------------------------------ list
  function renderList() {
    setChrome("recall");
    const m = DATA.meta;
    $("#sub").textContent = m.window_from ? `Major OEMs · Part 573 submissions ${m.window_from} – ${m.window_to} · ${upd(m)}` : upd(m);
    const items = DATA.items;
    if (DATA.meta.error) {
      view.innerHTML = `<p class="empty">${esc(DATA.meta.error)}</p>`;
      return;
    }
    if (!items.length) {
      view.innerHTML = `<p class="empty">No Part 573 reports from the selected manufacturers in the last ${days(m)} days.</p>`;
      return;
    }
    // NHTSA の公開日ごとにまとめる（新しく公開されたものが上）
    const pub = (it) => it.published || it.date;
    let html = newBar("recall"), cur = null;
    const byDay = {};
    items.forEach((it) => (byDay[pub(it)] = (byDay[pub(it)] || 0) + 1));
    for (const it of items) {
      if (pub(it) !== cur) {
        cur = pub(it);
        html += `<div class="day"><span>Published ${esc(fmtDate(cur))}</span><span>${byDay[cur]}</span></div>`;
      }
      const nw = isNew(it, DATA.meta);
      html += `<a class="card${nw ? " is-new" : ""}" href="#/r/${encodeURIComponent(it.id)}">
        <div class="row">${newBadge(it, DATA.meta)}<span class="tag">${esc(it.maker)}</span>${it.motorcycle ? '<span class="tag moto">Motorcycle</span>' : ""}
        ${it.amendment ? `<span class="badge-am">Amendment ${it.amendment > 90 ? "" : it.amendment}</span>` : ""}</div>
        <div class="subj">${esc(it.title || it.subject)}</div>
        <div class="row">${esc([it.nhtsa_id, `${it.total || "—"} units`, modelsShort(it)].filter(Boolean).join(" · "))}</div>
        <div class="row dates">Received ${esc(fmtShort(it.received || it.date))} · Published ${esc(fmtShort(pub(it)))}</div>
      </a>`;
    }
    html += `<p class="note">Grouped by the date NHTSA published each Part 573 report, newest first. "Received" is the date NHTSA received the report (for an amendment, the submission date on the report). Publication usually follows receipt by several days.</p>`;
    html += footer();
    view.innerHTML = html;
    window.scrollTo(0, +sessionStorage.getItem("listY:recall") || 0);
  }

  // ------------------------------------------------------------ investigations (PE / EA)
  const invModels = (it) => {
    const p = it.products || [];
    if (!p.length) return "";
    const s = p.slice(0, 2).map((x) => `${x.years ? x.years + " " : ""}${x.name}`);
    return p.length > 2 ? `${s.join(", ")} +${p.length - 2}` : s.join(", ");
  };
  // PE / EA の種別バッジ（色で区別）
  const typeBadge = (it) => `<span class="tag typ ${esc(it.type)}">${esc(it.type)}</span>`;
  const TYPE_NAME = { PE: "Preliminary Evaluation", EA: "Engineering Analysis", RQ: "Recall Query" };
  const evBadges = (it) => it.events.map((e) => `<span class="ev ${esc(e.kind)}">${esc(e.kind)}</span>`).join("");

  function renderInvList() {
    setChrome("inv");
    const m = INV.meta || {};
    $("#sub").textContent = m.window_from
      ? `All manufacturers · Opened or closed ${m.window_from} – ${m.window_to} · ${upd(m)}`
      : upd(m);
    const items = INV.items || [];
    if (m.error && !items.length) {
      view.innerHTML = `<p class="empty">${esc(m.error)}</p>`;
      return;
    }
    const n = (t) => items.filter((x) => x.type === t).length;
    const legend = `<div class="legend-inv">${["PE", "EA", "RQ"].map((t) => `<span><span class="tag typ ${t}">${t}</span> ${TYPE_NAME[t]} · ${n(t)}</span>`).join("")}</div>`;
    if (!items.length) {
      view.innerHTML = `${legend}<p class="empty">No PE, EA or RQ investigations opened or closed in the last ${days(m)} days.</p>${footer()}`;
      return;
    }
    let html = newBar("inv") + legend, cur = null;
    const byDay = {};
    items.forEach((it) => (byDay[it.date] = (byDay[it.date] || 0) + 1));
    for (const it of items) {
      if (it.date !== cur) {
        cur = it.date;
        html += `<div class="day"><span>${esc(fmtDate(cur))}</span><span>${byDay[cur]}</span></div>`;
      }
      html += `<a class="card inv ${esc(it.type)}${isNew(it, INV.meta) ? " is-new" : ""}" href="#/i/${encodeURIComponent(it.id)}">
        <div class="row">${newBadge(it, INV.meta)}${typeBadge(it)}<span class="tag">${esc(it.maker)}</span>${evBadges(it)}</div>
        <div class="subj">${esc(it.title || it.subject)}</div>
        <div class="row">${esc(it.id)}${it.components.length ? ` · ${esc(it.components[0])}` : ""}${invModels(it) ? ` · ${esc(invModels(it))}` : ""}</div>
      </a>`;
    }
    html += `<p class="note">Listed by the date the investigation was opened or closed (whichever falls in the window, latest first). The investigation list comes from NHTSA's daily ODI flat file, so a new investigation can appear a day late.</p>`;
    html += footer();
    view.innerHTML = html;
    window.scrollTo(0, +sessionStorage.getItem("listY:inv") || 0);
  }

  function renderInvDetail(id) {
    const it = (INV.items || []).find((x) => x.id === id);
    setChrome(null);
    if (!it) {
      view.innerHTML = `<p class="empty">This investigation is no longer in the ${days(INV.meta)}-day window.</p>`;
      return;
    }
    document.title = `${it.id} ${it.title || it.subject}`;
    $("#title").textContent = `${it.maker} · ${it.id}`;
    $("#sub").textContent = TYPE_NAME[it.type] || it.type;
    const prod = (arr) =>
      `<table class="veh"><tr><th>Make / Model</th><th style="text-align:right">MY</th></tr>` +
      arr.map((p) => `<tr><td>${esc(p.name)}</td><td class="n">${esc(p.years || "—")}</td></tr>`).join("") + `</table>`;
    const s1 = (it.summary || []).map((p) => `<p>${tap(p)}</p>`).join("");
    let s2 = it.products?.length ? prod(it.products) : "";
    if (it.other_products?.length)
      s2 += `<div class="lbl">Also listed by NHTSA</div><p class="parts">${esc(it.other_products.map((p) => `${p.years} ${p.name}`.trim()).join(", "))}</p>`;
    const s3 = (it.components || []).map((c) => `<p>${tap(c)}</p>`).join("");
    const s4 = it.recalls?.length ? `<p>${it.recalls.map(esc).join(", ")}</p>` : "";
    const s5 = it.docs?.length
      ? `<ul class="docs">${it.docs.map((d) => `<li><a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.label)} ↗</a>${d.date ? `<span class="dt">Posted ${esc(d.date)}</span>` : ""}</li>`).join("")}</ul>`
      : "";
    view.innerHTML = `
      <div class="hero">
        <div class="row" style="display:flex;gap:6px;flex-wrap:wrap">${newBadge(it, INV.meta)}${typeBadge(it)}<span class="tag">${esc(it.maker)}</span>${evBadges(it)}</div>
        <h2>${tap(it.title || it.subject)}</h2>
        <div class="meta">
          ${it.title && it.title !== it.subject ? `<span>NHTSA subject</span><b>${tap(it.subject)}</b>` : ""}
          <span>Action no.</span><b>${esc(it.id)}</b>
          <span>Opened</span><b>${it.opened ? esc(fmtDate(it.opened)) : "—"}</b>
          <span>Closed</span><b>${it.closed ? esc(fmtDate(it.closed)) : "Open"}</b>
          <span>Manufacturer</span><b>${esc(it.manufacturer || "—")}</b>
        </div>
      </div>
      ${section(1, it.closed ? "Summary (closing)" : "Summary", s1, false, false)}
      ${section(2, "Model year / Model", s2, false, false)}
      ${section(3, "Components", s3, false, false)}
      ${s4 ? section(4, "Related recalls", s4, false, false) : ""}
      ${section(s4 ? 5 : 4, "Documents", s5, false, false)}
      <p class="note">Tap an underlined word (Eiken Grade 2 / CEFR B1 and above) for its Japanese meaning.</p>
      ${footer()}`;
    window.scrollTo(0, 0);
  }

  function modelsShort(it) {
    const names = (it.vehicles || []).map((v) => v.name.replace(/^(\d{4})-(\d{4})/, (m, a, b) => (a === b ? a : `${a}-${b.slice(2)}`)));
    if (!names.length) return "";
    return names.length > 2 ? `${names.slice(0, 2).join(", ")} +${names.length - 2}` : names.join(", ");
  }

  // ------------------------------------------------------------ detail
  function paraHTML(p, tl) {
    if (p.startsWith("§")) return `<div class="d">${tap(p.slice(1))}</div>`;
    return `<p>${tap(p)}</p>`;
  }

  function diffHTML(rows, tl) {
    return rows
      .map((r) => {
        if (r.t === "eq") return paraHTML(r.x, tl);
        if (r.t === "ins" || r.t === "del") {
          const x = r.x.startsWith("§") ? r.x.slice(1) : r.x;
          const tag = r.x.startsWith("§") ? "div" : "p";
          return `<${tag} class="${r.t}${r.x.startsWith("§") ? " d" : ""}">${tap(x)}</${tag}>`;
        }
        const inner = r.ops
          .map(([op, t]) => (op === "=" ? tap(t) : `<span class="${op === "+" ? "ins" : "del"}">${tap(t)}</span>`))
          .join("");
        return `<p>${inner}</p>`;
      })
      .join("");
  }

  function block(key, paras, ch, tl) {
    if (ch && ch.sections && ch.sections[key]) return diffHTML(ch.sections[key], tl);
    return (paras || []).map((p) => paraHTML(p, tl)).join("");
  }

  function field(label, key, it, ch, fmt = (v) => esc(v)) {
    const v = it[key];
    const old = ch && ch.fields && ch.fields[key];
    if (!v && !old) return "";
    const oldHTML = old ? `<span class="old">${esc(old[0] || "—")}</span><span class="ins">${fmt(old[1] || "—")}</span>` : fmt(v);
    return `<div class="lbl">${esc(label)}</div><div>${oldHTML}</div>`;
  }

  function section(n, title, inner, changed, isAmend) {
    if (!inner) inner = `<p class="note" style="margin:0">Not stated in this report.</p>`;
    const flag = isAmend ? (changed ? `<span class="chg">Changed</span>` : `<span class="nochg">No change</span>`) : "";
    const open = !isAmend || changed ? " open" : "";
    return `<details class="sec"${open}><summary><span class="num">${n}</span>${esc(title)}${flag}</summary><div class="body">${inner}</div></details>`;
  }

  function renderDetail(id) {
    const it = DATA.items.find((x) => x.id === id);
    setChrome(null);
    if (!it) {
      view.innerHTML = `<p class="empty">This report is no longer in the ${days(DATA.meta)}-day window.</p>`;
      return;
    }
    document.title = `${it.nhtsa_id} ${it.title || it.subject}`;
    $("#title").textContent = `${it.maker} · ${it.nhtsa_id}`;
    $("#sub").textContent = `Published ${fmtDate(it.published || it.date)}`;
    const am = it.amendment > 0;
    const ch = am ? it.changes : null;
    const S = (ch && ch.sections) || {};
    const F = (ch && ch.fields) || {};

    let amendBox = "";
    if (am) {
      amendBox = ch
        ? `<div class="amend"><b>${esc(it.doc_label)}</b><br>Changes compared with <b>${esc(it.compared_with)}</b>.
            <div class="legend"><span class="ins">&nbsp;added&nbsp;</span><span class="del">&nbsp;deleted&nbsp;</span><span>Unchanged sections are collapsed.</span></div></div>`
        : `<div class="amend"><b>${esc(it.doc_label)}</b><br>The previous version has not been published by NHTSA, so no comparison is available.</div>`;
    }

    // 1 Defect
    const s1 =
      `<div class="lbl">Defect name</div><p>${tap(it.title || it.subject)}</p>` +
      (it.title && it.title !== it.subject ? `<div class="lbl">NHTSA subject</div><p>${tap(it.subject)}</p>` : "") +
      (it.defect?.length || S.defect ? `<div class="lbl">Description</div>${block("defect", it.defect, ch)}` : "") +
      (it.risk?.length || S.risk ? `<div class="lbl">Safety risk</div>${block("risk", it.risk, ch)}` : "") +
      (it.cause?.length || S.cause ? `<div class="lbl">Cause</div>${block("cause", it.cause, ch)}` : "");
    // 2 MY / Model
    let s2 = "";
    if (S.vehicles) {
      s2 = diffHTML(S.vehicles.map((r) => (r.t === "mod" ? r : r)), false);
    } else if (it.vehicles?.length) {
      s2 = `<table class="veh"><tr><th>MY / Model</th><th style="text-align:right">Units</th></tr>` +
        it.vehicles.map((v) => `<tr><td>${esc(v.name)}${v.category && /motorcycle/i.test(v.category) ? ' <span class="tag moto">Motorcycle</span>' : ""}${v.prod ? `<div class="parts">Built ${esc(v.prod)}</div>` : ""}</td><td class="n">${esc(v.count || "—")}</td></tr>`).join("") +
        `</table>`;
    }
    // 3 Components
    let s3 = "";
    if (S.components) s3 = diffHTML(S.components, false);
    else if (it.components?.length)
      s3 = it.components.map((c) => `<p>${tap(c.name.toLowerCase() === c.name ? c.name : c.name)}${c.parts?.length ? `<br><span class="parts">P/N: ${esc(c.parts.slice(0, 12).join(", "))}${c.parts.length > 12 ? ` … (+${c.parts.length - 12})` : ""}</span>` : ""}</p>`).join("");
    s3 += field("Supplier", "supplier", it, ch);
    // 4 Units
    const s4 = `<div class="big">${F.total ? `<span class="old" style="font-size:18px">${esc(F.total[0] || "—")}</span><span class="ins">${esc(F.total[1] || "—")}</span>` : esc(it.total || "—")}</div>` +
      field("Estimated percentage with defect", "pct", it, ch);
    // 5 Field incidents
    const s5 = S.market ? diffHTML(S.market) : (it.market || []).map((p) => `<p>${tap(p)}</p>`).join("");
    // 6 Chronology
    const s6 = `<div class="tl">${block("chronology", it.chronology, ch, true)}</div>`;
    // 7 Remedy
    const s7 = field("Remedy type", "remedy_type", it, ch) +
      (it.remedy?.length || S.remedy ? `<div class="lbl">Remedy program</div>${block("remedy", it.remedy, ch)}` : "") +
      (it.remedy_diff?.length || S.remedy_diff ? `<div class="lbl">How the remedy part differs</div>${block("remedy_diff", it.remedy_diff, ch)}` : "") +
      (it.production_fix?.length || S.production_fix ? `<div class="lbl">Production correction</div>${block("production_fix", it.production_fix, ch)}` : "");

    const c = (k) => !!(S[k] || F[k]);
    view.innerHTML = `
      <div class="hero">
        <div class="row" style="display:flex;gap:6px;flex-wrap:wrap">${newBadge(it, DATA.meta)}<span class="tag">${esc(it.maker)}</span>${it.motorcycle ? '<span class="tag moto">Motorcycle</span>' : ""}${am ? `<span class="badge-am">Amendment ${it.amendment > 90 ? "" : it.amendment}</span>` : ""}</div>
        <h2>${tap(it.title || it.subject)}</h2>
        <div class="meta">
          <span>NHTSA ID</span><b>${esc(it.nhtsa_id)}</b>
          <span>Received</span><b>${esc(fmtDate(it.received || it.date))}</b>
          <span>Published</span><b>${esc(fmtDate(it.published || it.date))}</b>
          <span>Manufacturer</span><b>${esc(it.manufacturer)}</b>
          ${it.mfr_campaign ? `<span>Mfr recall no.</span><b>${esc(it.mfr_campaign)}</b>` : ""}
        </div>
        <a class="pdf" href="${esc(it.doc_url)}" target="_blank" rel="noopener">Open Part 573 report (PDF) ↗</a>
        ${amendBox}
      </div>
      ${section(1, "Defect", s1, c("defect") || c("risk") || c("cause"), am)}
      ${section(2, "Model year / Model", s2, c("vehicles"), am)}
      ${section(3, "Components", s3, c("components") || c("supplier"), am)}
      ${section(4, "Units affected", s4, c("total") || c("pct"), am)}
      ${section(5, "Field incidents", s5, c("market"), am)}
      ${section(6, "Chronology", s6, c("chronology"), am)}
      ${section(7, "Remedy", s7, c("remedy") || c("remedy_diff") || c("production_fix") || c("remedy_type"), am)}
      <p class="note">Tap an underlined word (Eiken Grade 2 / CEFR B1 and above) for its Japanese meaning.</p>
      ${footer()}`;
    window.scrollTo(0, 0);
  }

  function footer() {
    return `<footer class="src">Source: NHTSA Part 573 Safety Recall Reports and ODI investigations (api.nhtsa.gov, static.nhtsa.gov). Japanese meanings: EJDict (public domain).
      Word levels: The CEFR-J Wordlist Version 1.5, compiled by Yukio Tono, Tokyo University of Foreign Studies; Octanove Vocabulary Profile C1/C2 (CC BY-SA 4.0).</footer>`;
  }

  // ------------------------------------------------------------ word sheet
  const sheet = $("#sheet");
  let onEl = null;
  function closeSheet() {
    sheet.hidden = true;
    if (onEl) onEl.classList.remove("on");
    onEl = null;
  }
  // 和訳の表示中は、どこをタップしても1回で閉じる（別の単語なら表示を切り替える）
  document.addEventListener("click", (e) => {
    const w = e.target.closest(".w");
    if (!sheet.hidden && (!w || w === onEl)) {
      e.preventDefault();
      closeSheet();
      return;
    }
    if (w) {
      e.preventDefault();
      const d = DICT[w.dataset.k];
      if (!d) return;
      if (onEl) onEl.classList.remove("on");
      onEl = w;
      w.classList.add("on");
      $("#sh-word").textContent = w.textContent;
      $("#sh-lv").textContent = d.g ? "Auto term" : d.l || "";
      $("#sh-head").textContent = d.h !== w.dataset.k ? `→ ${d.h}` : "";
      $("#sh-mean").textContent = d.m;
      sheet.hidden = false;
    }
  });

  // ------------------------------------------------------------ routing
  // #/recall #/inv = 一覧タブ、#/r/<id> = リコール明細、#/i/<id> = 調査明細（旧 #/pe #/ea は #/inv 扱い）
  const normTab = (t) => (t === "pe" || t === "ea" ? "inv" : t === "inv" || t === "recall" ? t : null);
  const curTab = () => {
    const m = location.hash.match(/^#\/(recall|inv|pe|ea)$/);
    if (m) return normTab(m[1]);
    if (!location.hash || location.hash === "#" || location.hash === "#/") return normTab(sessionStorage.getItem("tab")) || "recall";
    return null;
  };
  function route() {
    closeSheet();
    let m;
    if ((m = location.hash.match(/^#\/r\/(.+)$/))) return renderDetail(decodeURIComponent(m[1]));
    if ((m = location.hash.match(/^#\/i\/(.+)$/))) return renderInvDetail(decodeURIComponent(m[1]));
    const tab = curTab() || "recall";
    if (tab === "recall") renderList();
    else renderInvList();
  }
  window.addEventListener("hashchange", route);
  window.addEventListener("scroll", () => {
    const t = curTab();
    if (t) sessionStorage.setItem("listY:" + t, String(window.scrollY));
  }, { passive: true });
  // タブを切り替えたら、そのタブの前回スクロール位置に戻す（同じタブの再タップは先頭へ）
  document.querySelectorAll("#tabs a").forEach((a) =>
    a.addEventListener("click", (e) => {
      if (curTab() === a.dataset.tab) {
        e.preventDefault();
        sessionStorage.setItem("listY:" + a.dataset.tab, "0");
        window.scrollTo({ top: 0, behavior: "smooth" });
      } else if (!location.hash.match(/^#\/(recall|inv|pe|ea)$/)) {
        e.preventDefault();
        history.replaceState(null, "", a.getAttribute("href"));
        route();
      }
    })
  );
  $("#back").addEventListener("click", () => {
    if (history.length > 1) history.back();
    else location.hash = "#/" + (normTab(sessionStorage.getItem("tab")) || "recall");
  });

  load()
    .then(route)
    .catch((e) => {
      view.innerHTML = `<p class="empty">Could not load data. Check your connection and reload.<br><small>${esc(e.message)}</small></p>`;
    });

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
})();
