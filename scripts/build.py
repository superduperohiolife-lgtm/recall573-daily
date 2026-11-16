#!/usr/bin/env python3
"""NHTSA Part 573 届出を取得し、PWA 用の JSON を生成する。

処理の流れ
1. NHTSA API (safetyIssues/byDate) で直近の更新があったリコールを取得
2. 車両リコール (xxV) かつ対象メーカーに絞り込む
3. 573 レポート PDF（原本・改訂版）を取得し、本文から明細項目を抽出
4. 改訂版は直前の版と段落／単語単位で差分を取る
5. 提出日 (Submission Date) が過去 30 日以内の版を一覧化し JSON 出力
6. ODI 調査（PE / EA）のうち、過去 30 日以内に開始または終了したものを JSON 出力
7. 明細本文に出る単語のうち、英検2級（CEFR B1）以上の語だけ辞書サブセットを作成
"""
import collections
import difflib
import html
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "site", "data")
WINDOW_DAYS = int(os.environ.get("WINDOW_DAYS", "30"))
FETCH_MARGIN_DAYS = int(os.environ.get("FETCH_MARGIN_DAYS", str(WINDOW_DAYS + 7)))  # byDate は更新日基準のため、余裕を持って取得
API = "https://api.nhtsa.gov/safetyIssues/byDate?filter=recalls&dateStart={s}&dateEnd={e}&max=50&offset={o}"
# ODI 調査: 一覧は日次更新のフラットファイル、明細は byNhtsaId（byDate は調査を返さないため）
INV_FLAT = "https://static.nhtsa.gov/odi/ffdd/inv/FLAT_INV.zip"
INV_API = "https://api.nhtsa.gov/safetyIssues/byNhtsaId?nhtsaId={}"
INV_TYPES = ("PE", "EA")
UA = {"User-Agent": "recall573-daily (GitHub Actions; public NHTSA data)"}
JST = timezone(timedelta(hours=9))
PARSER_VERSION = "1"  # 解析ロジックを変えたら上げる（キャッシュ無効化）

# 対象メーカー（NHTSA の manufacturer 表記に対する正規表現 → 表示名）
MAKERS = [
    (r"^Honda \(American Honda", "Honda"),
    (r"^Toyota Motor Engineering", "Toyota"),
    (r"^Nissan North America", "Nissan"),
    (r"^Mazda", "Mazda"),
    (r"^Subaru of America", "Subaru"),
    (r"^Mitsubishi Motors North America", "Mitsubishi"),
    (r"^General Motors", "GM"),
    (r"^Ford Motor Company", "Ford"),
    (r"^Chrysler \(FCA US", "Stellantis"),
    (r"^Hyundai Motor America", "Hyundai"),
    (r"^Kia America", "Kia"),
    (r"^Genesis Motor", "Genesis"),
    (r"^Volkswagen Group of America", "VW Group"),
    (r"^BMW of North America", "BMW"),
    (r"^Mercedes-Benz USA", "Mercedes-Benz"),
    (r"^Daimler Vans USA", "Mercedes-Benz"),
    (r"^Tesla", "Tesla"),
    (r"^Volvo Car USA", "Volvo"),
]
MOTORCYCLE_OK = {"Honda"}  # 二輪を含めるのは Honda のみ


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def http_get(url, binary=False, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
            return data if binary else data.decode("utf-8")
        except Exception as e:  # noqa: BLE001
            log(f"  retry {i + 1}/{tries}: {url} ({e})")
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"GET failed: {url}")


def fetch_recalls(start, end):
    out, off = [], 0
    while True:
        d = json.loads(http_get(API.format(s=start, e=end, o=off)))
        recs = [r for res in d.get("results", []) for r in res.get("recalls", [])]
        out += recs
        total = d["meta"]["pagination"]["total"]
        off += 50
        if off >= total or not recs:
            break
        time.sleep(0.3)
    return out


def maker_of(name):
    for pat, label in MAKERS:
        if re.search(pat, name or "", re.I):
            return label
    return None


# ---------------------------------------------------------------- PDF 解析
NOISE = [
    re.compile(r"^The information contained in this report was submitted pursuant to 49 CFR"),
    re.compile(r"^Page \d+ of \d+$"),
    re.compile(r"^Part 573 Safety Recall Report$"),
    re.compile(r"^\d{2}[VETC]\d{3}$"),
    re.compile(r"^OMB Control No"),
]
DATE_LINE = re.compile(
    r"^((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}(st|nd|rd|th)?,?\s+)?\d{4}"
    r"(\s*[-–]\s*\w+\.?(\s+\d{1,2},?)?\s*\d{0,4})?|"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*[-–]\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"(Early|Mid|Late|Mid-|Early-|Late-)\s*\w+\s+\d{4}|Q[1-4]\s+\d{4})\s*:?$",
    re.I,
)


def pdf_text(pdf_bytes):
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "a.pdf")
        with open(p, "wb") as f:
            f.write(pdf_bytes)
        txt = subprocess.run(["pdftotext", p, "-"], capture_output=True, check=True).stdout
    txt = txt.decode("utf-8", "replace").replace("\r", "").replace("\f", "\n")
    return [ln.rstrip() for ln in txt.split("\n") if not any(n.search(ln.strip()) for n in NOISE)]


def between(lines, start_pat, end_pats):
    """start_pat に一致する行の次から end_pats のいずれかの直前までを返す。"""
    s = None
    for i, ln in enumerate(lines):
        if re.search(start_pat, ln.strip()):
            s = i
            break
    if s is None:
        return []
    first = re.sub(start_pat, "", lines[s].strip()).strip()
    body = [first] if first else []
    for ln in lines[s + 1:]:
        if any(re.search(p, ln.strip()) for p in end_pats):
            break
        body.append(ln)
    return body


MONTHS = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
PARA_START = re.compile(r"^((On|In|As of|From|Between|During|Since|By|Through)\s+(early |mid-?|late )?" + MONTHS
                        + r"|" + MONTHS + r"\s+\d{1,2}(st|nd|rd|th)?,?\s+\d{4}\s*[-–:]|\d{1,2}/\d{1,2}/\d{2,4}\s*[-–:])")


def paragraphs(lines, date_heads=False):
    """改行で分断された行を段落に再構成する（空行はページ区切り由来のため無視）。"""
    paras, cur = [], []

    def flush():
        if cur:
            t = re.sub(r"\s+", " ", " ".join(cur)).strip()
            t = re.sub(r"\s+([,.;:])", r"\1", t)
            if t:
                paras.append(t)
            cur.clear()

    for raw in lines:
        ln = raw.strip()
        if not ln:
            continue
        if date_heads and DATE_LINE.match(ln):
            flush()
            paras.append("§" + ln.rstrip(":"))  # § = 日付見出し
            continue
        if cur and re.search(r"[.:;!?][\"”)]?$", cur[-1]) and PARA_START.match(ln):
            flush()
        cur.append(ln)
        if len(ln) < 85 and re.search(r"[.:;!?][\"”)]?$", ln):
            flush()
    flush()
    return paras


SECTION_ENDS_DEFECT = [r"^FMVSS\s*1:", r"^Description of the safety risk", r"^Description of the cause:",
                       r"^Identification of any warning", r"^Component Manufacturer$", r"^Involved Components$"]


def parse_573(lines):
    text = "\n".join(lines)
    g = lambda pat: (re.search(pat, text) or [None, None])[1]  # noqa: E731
    r = {
        "submission_date": g(r"Submission Date:\s*([A-Z][a-z]{2} \d{1,2}, \d{4})"),
        "total": g(r"Total number of potentially involved:\s*([\d,]+)"),
        "pct": g(r"Estimated percentage with defect:\s*([\d.<>]+\s*%)"),
        "remedy_type": g(r"Remedy Type:[ \t]*([^\n]*)"),
    }
    if r["remedy_type"]:
        r["remedy_type"] = re.sub(r"\s*(Address|Consumer Advisories):.*$", "", r["remedy_type"]).strip() or None
    # 車両
    veh_lines = between(lines, r"^Vehicle Information$", [r"^Defect / Noncompliance Description$"])
    vehicles, cur = [], None
    it = iter(veh_lines)
    for ln in it:
        s = ln.strip()
        if re.match(r"^Vehicle \d+:$", s):
            cur = {"name": None, "category": None, "type": None, "prod": None, "count": None}
            vehicles.append(cur)
            continue
        if cur is None or not s:
            continue
        if cur["name"] is None and re.match(r"^\d{4}-\d{4}\s+\S", s):
            cur["name"] = s
        elif s == "Product Category:":
            nx = next(it, "").strip()
            cur["category"] = None if nx.endswith(":") else nx
        elif s == "Production Dates:":
            cur["prod"] = next(it, "").strip()
        elif s.startswith("Number of potentially involved:"):
            cur["count"] = s.split(":", 1)[1].strip()
    r["vehicles"] = [v for v in vehicles if v["name"]]

    end_all = SECTION_ENDS_DEFECT
    r["defect"] = paragraphs(between(lines, r"^Description of the defect or noncompliance:", end_all))
    r["risk"] = paragraphs(between(lines, r"^Description of the safety risk, including crash, fire, death, injury:", end_all))
    r["cause"] = paragraphs(between(lines, r"^Description of the cause:", end_all))
    # 部品
    sup = between(lines, r"^Component Manufacturer$", [r"^Involved Components$"])
    names = [x.strip() for x in sup]
    r["supplier"] = None
    for i, x in enumerate(names):
        if x == "Name:" and i + 1 < len(names):
            r["supplier"] = names[i + 1]
            break
        if x.startswith("Name:") and len(x) > 5:
            r["supplier"] = x[5:].strip()
            break
    comp_lines = between(lines, r"^Involved Components$", [r"^Chronology$", r"^Description of Remedy$"])
    comps = {}
    cur_name = None
    it = iter(comp_lines)
    for ln in it:
        s = ln.strip()
        if re.match(r"^Component Name \d+:", s):
            nm = s.split(":", 1)[1].strip() or next(it, "").strip()
            if nm.startswith("Component Description:"):
                nm = nm.split(":", 1)[1].strip()
            cur_name = nm
            comps.setdefault(nm, [])
        elif s.startswith("Component Part Number:") and cur_name:
            pn = s.split(":", 1)[1].strip()
            if pn and pn not in comps[cur_name]:
                comps[cur_name].append(pn)
    r["components"] = [{"name": k, "parts": v} for k, v in comps.items() if k]
    # クロノロジー
    chrono_raw = between(lines, r"^Chronology$", [r"^Related NHTSA Recall Number", r"^Description of Remedy$"])
    r["chronology"] = paragraphs(chrono_raw, date_heads=True)
    # 市場発生状況（クロノロジー中の件数記述の文を抽出）
    market = []
    date_re = re.compile(MONTHS + r"\s+\d{1,2}(st|nd|rd|th)?(,?\s+\d{4})?|\b(19|20)\d{2}\b|\d{1,2}/\d{1,2}/\d{2,4}", re.I)
    cnt = re.compile(r"\b(\d[\d,.]*|zero|no|not|any|none|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b"
                     r"[^.;]{0,80}?\b(warranty|claims?|field reports?|reports?|complaints?|incidents?|injur\w*|deaths?|"
                     r"fatalit\w*|fires?|crash\w*|accidents?|VOQs?|allegations?|repairs? per|failures?|occurrences?)\b", re.I)
    for p in r["chronology"]:
        if p.startswith("§"):
            continue
        for sent in re.split(r"(?<=[.;])\s+(?=[A-Z])", p):
            probe = re.sub(r"Part 573|\b\d{2}[VETC]-?\d{3}(\d{3})?\b", " ", date_re.sub(" ", sent))
            if cnt.search(probe) and sent not in market:
                market.append(sent)
    r["market"] = market
    # 修理手法
    rem_end = [r"^How remedy component differs", r"^Identify how/when recall condition", r"^Reimbursement Plan$",
               r"^Recall Schedule$"]
    r["remedy"] = paragraphs(between(lines, r"^Description of remedy program:", rem_end))
    r["remedy_diff"] = paragraphs(between(lines, r"^How remedy component differs from recalled component:", rem_end))
    r["production_fix"] = paragraphs(between(lines, r"^Identify how/when recall condition was corrected in production:", rem_end))
    return r


# ---------------------------------------------------------------- 差分
DIFF_KEYS = ["defect", "risk", "cause", "market", "chronology", "remedy", "remedy_diff", "production_fix"]


def word_ops(a, b):
    ta, tb = re.findall(r"\S+|\s+", a), re.findall(r"\S+|\s+", b)
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        if tag == "equal":
            ops.append(["=", "".join(ta[i1:i2])])
        else:
            if i2 > i1:
                ops.append(["-", "".join(ta[i1:i2])])
            if j2 > j1:
                ops.append(["+", "".join(tb[j1:j2])])
    return ops


def diff_paras(old, new):
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            out += [{"t": "eq", "x": p} for p in new[j1:j2]]
        elif tag == "replace" and (i2 - i1) == (j2 - j1):
            for a, b in zip(old[i1:i2], new[j1:j2]):
                if difflib.SequenceMatcher(None, a, b).ratio() > 0.5:
                    out.append({"t": "mod", "ops": word_ops(a, b)})
                else:
                    out += [{"t": "del", "x": a}, {"t": "ins", "x": b}]
        else:
            out += [{"t": "del", "x": p} for p in old[i1:i2]]
            out += [{"t": "ins", "x": p} for p in new[j1:j2]]
    return out


def summarize_changes(old, new):
    changed = {}
    for k in DIFF_KEYS:
        if old.get(k) != new.get(k):
            changed[k] = diff_paras(old.get(k) or [], new.get(k) or [])
    scal = {}
    for k in ["total", "pct", "remedy_type", "supplier"]:
        if old.get(k) != new.get(k):
            scal[k] = [old.get(k), new.get(k)]
    ovm = {v["name"]: v.get("count") for v in old.get("vehicles", [])}
    nvm = {v["name"]: v.get("count") for v in new.get("vehicles", [])}
    if ovm != nvm:
        rows = []
        for n, c in nvm.items():
            if n not in ovm:
                rows.append({"t": "ins", "x": f"{n} ({c})"})
            elif ovm[n] != c:
                rows.append({"t": "mod", "ops": [["=", f"{n} ("], ["-", ovm[n] or "—"], ["+", c or "—"], ["=", ")"]]})
            else:
                rows.append({"t": "eq", "x": f"{n} ({c})"})
        rows += [{"t": "del", "x": f"{n} ({c})"} for n, c in ovm.items() if n not in nvm]
        changed["vehicles"] = rows
    oc = [c["name"] for c in old.get("components", [])]
    nc = [c["name"] for c in new.get("components", [])]
    if oc != nc:
        changed["components"] = diff_paras(oc, nc)
    return {"sections": changed, "fields": scal}


# ---------------------------------------------------------------- 辞書
def load_dict(ej_dir, cefr_csv, c1c2_csv, glossary_tsv):
    ej = {}
    src = os.path.join(ej_dir, "src")
    for fn in sorted(os.listdir(src)):
        with open(os.path.join(src, fn), encoding="utf-8") as f:
            for ln in f:
                if "\t" not in ln:
                    continue
                w, m = ln.rstrip("\n").split("\t", 1)
                for k in w.split(","):
                    k = k.strip().lower()
                    if k and k not in ej:
                        ej[k] = m
    level = {}
    import csv
    for fn in (cefr_csv, c1c2_csv):
        with open(fn, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                lv = (row.get("CEFR") or "").strip()
                for hw in row["headword"].split("/"):
                    hw = hw.strip().lower()
                    if hw and (hw not in level or lv < level[hw]):
                        level[hw] = lv
    gl = {}
    with open(glossary_tsv, encoding="utf-8") as f:
        for ln in f:
            if ln.startswith("#") or "\t" not in ln:
                continue
            w, m = ln.rstrip("\n").split("\t", 1)
            gl[w.strip().lower()] = m.strip()
    return ej, level, gl


def lemma_candidates(w):
    c = [w]
    rules = [("ies", "y"), ("ied", "y"), ("ves", "f"), ("es", ""), ("s", ""), ("ed", ""), ("ed", "e"), ("ing", ""),
             ("ing", "e"), ("ier", "y"), ("iest", "y"), ("er", ""), ("est", ""), ("ly", ""), ("ily", "y"), ("'s", "")]
    for suf, rep in rules:
        if w.endswith(suf) and len(w) - len(suf) >= 2:
            base = w[: -len(suf)] + rep
            c.append(base)
            if suf in ("ed", "ing", "er", "est") and len(base) > 2 and base[-1] == base[-2]:
                c.append(base[:-1])  # stopped -> stop
    return c


def short_meaning(m, n=140):
    m = re.sub(r"\s+", " ", m).strip()
    parts = [p.strip() for p in m.split(" / ") if p.strip()]
    s = " / ".join(parts[:4])
    return s if len(s) <= n else s[: n - 1] + "…"


def build_dict(texts, ej, level, gl):
    words = set()
    for t in texts:
        for w in re.findall(r"[A-Za-z][A-Za-z'-]*[A-Za-z]|[A-Za-z]", t):
            if len(w) > 1 and w.isupper():
                continue  # 略語・型式（EPS, ACURA 等）は対象外
            words.add(w.lower())
    out = {}
    for w in sorted(words):
        cands = lemma_candidates(w)
        g = next((c for c in cands if c in gl), None)
        if g:
            out[w] = {"h": g, "m": gl[g], "g": 1}
            continue
        head = next((c for c in cands if c in ej), None)
        if not head:
            continue
        lv = next((level[c] for c in cands if c in level), None)
        if lv and lv[:2] in ("A1", "A2"):
            continue  # 英検2級（B1）未満は対象外
        if len(head) <= 2:
            continue
        out[w] = {"h": head, "m": short_meaning(ej[head]), "l": (lv or "")[:2]}
    return out


# ---------------------------------------------------------------- ODI 調査（PE / EA）
def _ymd(s):
    """YYYYMMDD または ISO 文字列 → date（空なら None）。"""
    s = (s or "").strip()
    if re.fullmatch(r"\d{8}", s):
        return datetime.strptime(s, "%Y%m%d").date()
    if re.match(r"\d{4}-\d{2}-\d{2}", s):
        return datetime.fromisoformat(s[:10]).date()
    return None


def flat_investigations(cutoff):
    """フラットファイルから、期間内に開始・終了した PE/EA の番号と付随情報を返す。"""
    z = zipfile.ZipFile(io.BytesIO(http_get(INV_FLAT, binary=True)))
    name = next(n for n in z.namelist() if n.upper().endswith(".TXT"))
    hits, last_no = {}, collections.defaultdict(int)
    with z.open(name) as f:
        for raw in io.TextIOWrapper(f, encoding="cp1252", errors="replace"):
            p = raw.rstrip("\r\n").split("\t")
            if len(p) < 9 or p[0][:2] not in INV_TYPES:
                continue
            m = re.fullmatch(r"(PE|EA)(\d{2})(\d{3})", p[0])
            if m:
                last_no[(m[1], m[2])] = max(last_no[(m[1], m[2])], int(m[3]))
            od, cd = _ymd(p[6]), _ymd(p[7])
            if not ((od and od >= cutoff) or (cd and cd >= cutoff)):
                continue
            h = hits.setdefault(p[0], {"odate": od, "cdate": cd, "mfr": collections.Counter(), "camp": set()})
            h["mfr"][p[5].strip()] += 1
            if p[8].strip():
                h["camp"].add(p[8].strip())
    return hits, last_no


def html_paras(s):
    paras = []
    for chunk in re.split(r"(?i)</p>|<br\s*/?>|</div>|</li>", s or ""):
        t = html.unescape(re.sub(r"<[^>]+>", " ", chunk)).replace("\xa0", " ")
        t = re.sub(r"\s+", " ", t).strip()
        if t:
            paras.append(t)
    return paras


def clean_mfr(name):
    n = re.sub(r",?\s*(Inc\.?|LLC|L\.L\.C\.|Corp\.?|Corporation|Co\.)$", "", (name or "").strip(), flags=re.I)
    return re.sub(r",\s*$", "", n).strip() or name


def products_view(products, primary):
    """製品一覧を「メーカー表記 → 車名 → 年式」にまとめる。主要メーカー以外は別枠。"""
    main, other = collections.OrderedDict(), collections.OrderedDict()
    for p in products or []:
        key = f"{(p.get('productMake') or '').strip()} {(p.get('productModel') or '').strip()}".strip()
        if not key:
            continue
        bucket = main if (p.get("manufacturer") or "") == primary else other
        bucket.setdefault(key, set())
        y = (p.get("productYear") or "").strip()
        if y.isdigit() and y != "9999":  # 9999 = 年式なし（装備品・ADS 等）
            bucket[key].add(int(y))

    def fmt(b):
        out = []
        for k, ys in b.items():
            ys = sorted(ys)
            rng = "" if not ys else (str(ys[0]) if len(ys) == 1 else f"{ys[0]}-{ys[-1]}")
            if ys and len(ys) != ys[-1] - ys[0] + 1:
                rng = ", ".join(map(str, ys))  # 年式に欠けがあれば列挙
            out.append({"name": k, "years": rng})
        return sorted(out, key=lambda x: x["name"])

    return fmt(main), fmt(other)


def build_investigations(cutoff, today):
    hits, last_no = flat_investigations(cutoff)
    log(f"investigations in flat file window: {sorted(hits)}")
    # フラットファイル更新前の新規開始分を拾うため、各種別の最新番号の次を数件だけ照会
    yy = f"{today.year % 100:02d}"
    probe = []
    for t in INV_TYPES:
        n = last_no.get((t, yy), 0)
        probe += [f"{t}{yy}{n + i:03d}" for i in range(1, 4)]

    items = []
    for no in sorted(hits) + probe:
        time.sleep(0.3)
        try:
            d = json.loads(http_get(INV_API.format(no)))
        except Exception as e:  # noqa: BLE001
            log(f"  ! investigation fetch failed {no}: {e}")
            continue
        invs = [x for res in d.get("results", []) for x in res.get("investigations", [])]
        if not invs:
            continue
        v = invs[0]
        h = hits.get(no, {"odate": None, "cdate": None, "mfr": collections.Counter(), "camp": set()})
        od = h["odate"] or _ymd(v.get("dateOpened"))
        cd = h["cdate"] or _ymd(v.get("dateClosed"))
        events = []
        if od and od >= cutoff:
            events.append({"kind": "Opened", "date": od.isoformat()})
        if cd and cd >= cutoff:
            events.append({"kind": "Closed", "date": cd.isoformat()})
        if not events:
            continue
        prods = v.get("associatedProducts") or []
        primary = h["mfr"].most_common(1)[0][0] if h["mfr"] else None
        if not primary:
            c = collections.Counter(p.get("manufacturer") for p in prods if p.get("manufacturer"))
            primary = c.most_common(1)[0][0] if c else ""
        main_p, other_p = products_view(prods, primary)
        docs = sorted(v.get("associatedDocuments") or [], key=lambda x: x.get("loadDate") or "")
        recalls = sorted({r.get("nhtsaCampaignNumber") for r in v.get("recalls") or [] if r.get("nhtsaCampaignNumber")}
                         | h["camp"])
        typ = v.get("type") or no[:2]
        items.append({
            "id": no,
            "type": typ,
            "date": max(e["date"] for e in events),
            "events": events,
            "opened": od.isoformat() if od else None,
            "closed": cd.isoformat() if cd else None,
            "status": "Closed" if cd else "Open",
            "maker": maker_of(primary) or clean_mfr(primary) or "—",
            "manufacturer": primary,
            "subject": (v.get("subject") or "").strip(),
            "summary": html_paras(v.get("summary")),
            "components": [c.get("name") for c in v.get("components") or [] if c.get("name")],
            "products": main_p,
            "other_products": other_p,
            "recalls": recalls,
            "docs": [{"label": (x.get("summary") or x.get("fileName") or "").strip(), "url": x.get("url"),
                      "date": (x.get("loadDate") or "")[:10]} for x in docs if x.get("url")],
        })
        log(f"  + {no} {items[-1]['maker']} {[e['kind'] for e in events]} {items[-1]['subject']}")
    items.sort(key=lambda x: (x["date"], x["id"]), reverse=True)
    return items


# ---------------------------------------------------------------- main
def main():
    today = datetime.now(JST).date()
    start = today - timedelta(days=FETCH_MARGIN_DAYS)
    cutoff = today - timedelta(days=WINDOW_DAYS)
    log(f"today(JST)={today} window>={cutoff}")
    recs = fetch_recalls(start.isoformat(), (today + timedelta(days=1)).isoformat())
    log(f"recalls fetched: {len(recs)}")

    cache_dir = os.environ.get("PDF_CACHE", os.path.join(ROOT, ".cache"))
    os.makedirs(cache_dir, exist_ok=True)
    for fn in os.listdir(cache_dir):  # 60日超・旧バージョンのキャッシュを削除
        fp = os.path.join(cache_dir, fn)
        if not fn.startswith(f"v{PARSER_VERSION}_") or time.time() - os.path.getmtime(fp) > 60 * 86400:
            os.remove(fp)

    def get_parsed(url):
        key = os.path.join(cache_dir, f"v{PARSER_VERSION}_" + re.sub(r"[^A-Za-z0-9._-]", "_", url.rsplit("/", 1)[-1]) + ".json")
        if os.path.exists(key):
            with open(key, encoding="utf-8") as f:
                return json.load(f)
        time.sleep(0.3)
        p = parse_573(pdf_text(http_get(url, binary=True)))
        with open(key, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False)
        return p

    items = []
    for r in recs:
        camp = r.get("nhtsaCampaignNumber", "")
        if len(camp) < 3 or camp[2] != "V":
            continue
        mk = maker_of(r.get("manufacturer"))
        if not mk:
            continue
        docs = [d for d in r.get("associatedDocuments", [])
                if d.get("fileName", "").upper().startswith("RCLRPT") and "573" in d.get("summary", "")]
        if not docs:
            continue

        def amend_no(d):
            m = re.search(r"Amendment\s*(\d+)", d["summary"], re.I)
            return int(m.group(1)) if m else (99 if "amend" in d["summary"].lower() else 0)

        docs.sort(key=lambda d: (amend_no(d), d.get("loadDate", "")))
        prev = None
        for d in docs:
            no = amend_no(d)
            load = (d.get("loadDate") or "")[:10]
            # 古い版は差分の比較元としてのみ使用（取得は必要時のみ）
            if load and load < start.isoformat() and d is not docs[-1]:
                prev = (d, None)
                continue
            try:
                p = get_parsed(d["url"])
            except Exception as e:  # noqa: BLE001
                log(f"  ! parse failed {d['url']}: {e}")
                continue
            sd = None
            if p.get("submission_date"):
                sd = datetime.strptime(p["submission_date"], "%b %d, %Y").date()
            elif no == 0 and r.get("reportReceivedDate"):
                sd = datetime.fromisoformat(r["reportReceivedDate"][:10]).date()
            if not sd or sd < cutoff:
                prev = (d, p)
                continue
            if no > 0 and veh_all_motorcycle(p) and mk not in MOTORCYCLE_OK:
                prev = (d, p)
                continue
            if veh_all_motorcycle(p) and mk not in MOTORCYCLE_OK:
                prev = (d, p)
                continue
            item = {
                "id": f"{camp}-{no}",
                "campaign": camp,
                "nhtsa_id": camp[:6],
                "amendment": no,
                "date": sd.isoformat(),
                "maker": mk,
                "manufacturer": r.get("manufacturer"),
                "mfr_campaign": r.get("mfrCampaignNumber"),
                "subject": r.get("subject"),
                "doc_url": d["url"],
                "doc_label": d["summary"].strip(),
                "motorcycle": veh_all_motorcycle(p),
                **p,
            }
            if no > 0:
                if prev is not None:
                    pd_, pp = prev
                    if pp is None:
                        try:
                            pp = get_parsed(pd_["url"])
                        except Exception as e:  # noqa: BLE001
                            log(f"  ! prev parse failed {pd_['url']}: {e}")
                    if pp is not None:
                        item["changes"] = summarize_changes(pp, p)
                        item["compared_with"] = pd_["summary"].strip()
                if "changes" not in item:
                    item["changes"] = None
            items.append(item)
            prev = (d, p)
            log(f"  + {item['id']} {mk} {sd} {r.get('subject')}")

    items.sort(key=lambda x: (x["date"], x["campaign"], x["amendment"]), reverse=True)

    # ODI 調査（失敗してもリコール側は出力する）
    inv_meta = {"generated_at": datetime.now(JST).isoformat(timespec="minutes"), "window_from": cutoff.isoformat(),
                "window_to": today.isoformat()}
    try:
        invs = build_investigations(cutoff, today)
    except Exception as e:  # noqa: BLE001
        log(f"  ! investigations failed: {e}")
        invs = []
        inv_meta["error"] = "Could not load NHTSA investigation data in the latest update."
    inv_meta["count"] = len(invs)

    # 辞書サブセット
    ext = os.environ.get("EXT_DIR", os.path.join(ROOT, ".ext"))
    texts = []
    for it in items:
        for k in DIFF_KEYS + ["subject"]:
            v = it.get(k)
            texts += v if isinstance(v, list) else [v or ""]
        for c in it.get("components", []):
            texts.append(c["name"].lower())
        if it.get("changes"):
            texts.append(json.dumps(it["changes"]["sections"]))
    for it in invs:
        texts += [it["subject"]] + it["summary"] + [c.lower() for c in it["components"]]
    ej, level, gl = load_dict(os.path.join(ext, "EJDict"),
                              os.path.join(ext, "olp-en-cefrj", "cefrj-vocabulary-profile-1.5.csv"),
                              os.path.join(ext, "olp-en-cefrj", "octanove-vocabulary-profile-c1c2-1.0.csv"),
                              os.path.join(ROOT, "scripts", "glossary.tsv"))
    dic = build_dict(texts, ej, level, gl)

    os.makedirs(OUT_DIR, exist_ok=True)
    meta = {"generated_at": datetime.now(JST).isoformat(timespec="minutes"), "window_from": cutoff.isoformat(),
            "window_to": today.isoformat(), "count": len(items)}
    with open(os.path.join(OUT_DIR, "items.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "items": items}, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(OUT_DIR, "inv.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": inv_meta, "items": invs}, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(OUT_DIR, "dict.json"), "w", encoding="utf-8") as f:
        json.dump(dic, f, ensure_ascii=False, separators=(",", ":"))
    log(f"items={len(items)} investigations={len(invs)} dict={len(dic)}")


def veh_all_motorcycle(p):
    v = p.get("vehicles") or []
    return bool(v) and all((x.get("category") or "").lower().startswith("motorcycle") for x in v)


if __name__ == "__main__":
    main()
