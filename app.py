import os, re, io, uuid, time, json, hashlib, threading, warnings, datetime as dt
from typing import List, Dict, Any
from urllib.parse import urljoin, urlsplit, urldefrag, parse_qsl, urlencode, urlunsplit

warnings.filterwarnings("ignore")

from flask import Flask, request, jsonify, send_file, render_template
import pandas as pd
import requests
from PIL import Image

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# our fixer
from fixer import extract_php_targets, fix_selected

# ------------------------ App setup ------------------------
app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = os.path.abspath("./uploads")
app.config["REPORT_FOLDER"] = os.path.abspath("./reports")
app.config["SHOT_ROOT"] = os.path.abspath("./shots")

for d in (app.config["UPLOAD_FOLDER"], app.config["REPORT_FOLDER"], app.config["SHOT_ROOT"]):
    os.makedirs(d, exist_ok=True)

JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()

TESTER = "Mongoo"
CHECK_TEXT = 'ページにアクセスした際に、警告やエラーが発生していないか確認します。'

# ------------------------ Error patterns ------------------------
STRONG_ERROR_PATTERNS = [
    r"not\s+found", r"page\s+not\s+found", r"forbidden", r"unauthorized",
    r"internal\s+server\s+error", r"bad\s+gateway", r"service\s+unavailable",
    r"application\s+error", r"stack\s+trace", r"exception", r"traceback",
    r"fatal\s+error", r"sqlstate", r"database\s+error",
    r"cannot\s+(get|post)\s+/", r"typeerror", r"referenceerror", r"syntaxerror",
    r"undefined\s+(index|variable|offset|array\s+key)", r"parse\s+error",
]
WEAK_ERROR_PATTERNS = [r"\bwarning\b", r"\bnotice\b", r"whoops",  r"deprecated"]
ERROR_RE_STRONG = re.compile("|".join(STRONG_ERROR_PATTERNS), re.I | re.S)
ERROR_RE_WEAK   = re.compile("|".join(WEAK_ERROR_PATTERNS), re.I | re.S)

# ------------------------ AI health (optional) ------------------------
def ai_health() -> dict:
    model = os.environ.get("AI_MODEL", "gpt-4o-mini")
    t0 = time.time()
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return {"ok": False, "model": model, "latency_ms": int((time.time()-t0)*1000), "error": "NoKey"}
    try:
        from openai import OpenAI
        client = OpenAI()
        client.chat.completions.create(
            model=model,
            messages=[{"role":"system","content":"healthcheck"},{"role":"user","content":"ping"}],
            temperature=0.0,
            max_tokens=1,
        )
        return {"ok": True, "model": model, "latency_ms": int((time.time()-t0)*1000), "error": None}
    except Exception as e:
        return {"ok": False, "model": model, "latency_ms": int((time.time()-t0)*1000), "error": f"{type(e).__name__}: {e}"}

# ------------------------ Helpers ------------------------
def now_str():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def normalize_url(u: str, base: str, keep_query: bool = True) -> str:
    if not u:
        return ""
    u = u.strip()
    if not (u.startswith("http://") or u.startswith("https://")):
        u = urljoin(base, u)
    u, _ = urldefrag(u)
    p = urlsplit(u)
    path = p.path or "/"
    path = re.sub(r"//+", "/", path)
    query = p.query if keep_query else ""
    if keep_query and p.query:
        q = parse_qsl(p.query, keep_blank_values=True)
        q.sort()
        query = urlencode(q, doseq=True)
    return urlunsplit((p.scheme, p.netloc, path, query, ""))

def url_to_shot(job_id: str, url: str) -> str:
    key = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
    d = os.path.join(app.config["SHOT_ROOT"], f"job_{job_id}")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{key}.png")

def detect_error_note(text_lower: str) -> str:
    hits = []
    if ERROR_RE_STRONG.search(text_lower or ""):
        for pat in STRONG_ERROR_PATTERNS:
            if re.search(pat, text_lower or "", re.I | re.S):
                hits.append(pat)
    if ERROR_RE_WEAK.search(text_lower or ""):
        if len(ERROR_RE_WEAK.findall(text_lower or "")) >= 3:
            hits.append("multiple weak warnings/notices")
    return " | ".join(hits[:10])

def fullpage_screenshot(driver, out_path: str):
    try:
        h = driver.execute_script("""
            return Math.max(
                document.body.scrollHeight, document.body.offsetHeight,
                document.documentElement.clientHeight, document.documentElement.scrollHeight,
                document.documentElement.offsetHeight);
        """) or 1200
        h = max(800, min(int(h), 5000))
        driver.set_window_size(1366, h)
        driver.save_screenshot(out_path)
    except Exception:
        driver.save_screenshot(out_path)

# -------- Docker/host path remapping --------
def _load_path_maps():
    try:
        maps = json.loads(os.environ.get("PATH_MAPS", "[]"))
    except Exception:
        maps = []
    if not maps:
        maps = [{"from": "/home/www-virtual/kangoiryo.jp",
                 "to": r"D:\XAMPP\htdocs\kangoiryo.jp\branches\mungunshagai"}]
    maps = [m for m in maps if isinstance(m, dict) and m.get("from") and m.get("to")]
    maps.sort(key=lambda m: len(str(m["from"])), reverse=True)
    return maps

_PATH_MAPS = _load_path_maps()

def remap_host_path(path_in: str) -> str:
    if not path_in:
        return path_in
    u = str(path_in).replace("\\", "/")
    for m in _PATH_MAPS:
        src = str(m["from"]).rstrip("/").replace("\\", "/")
        if u.startswith(src):
            tail = u[len(src):]
            dst = str(m["to"]).rstrip("\\/")
            remapped = dst + tail.replace("/", os.sep)
            return os.path.normpath(remapped)
    return os.path.normpath(path_in)

# ------------------------ Japanese-grid writer ------------------------
def write_with_images_fit(
    df: pd.DataFrame,
    out_path: str,
    image_col: str = "screenshot_path",
    display_col_name: str = "スクリーンショット",
    col_width_chars: float = 0.0
):
    import xlsxwriter, math
    from typing import Any

    SCHEMA = [
        ("番号",           "row_no",       4),
        ("テスト確認項目",  "title",       36),
        ("枝番",           "edaban",       5),
        ("実施方法",       "url",         28),
        ("確認する内容",    "check_text",  48),
        ("確認者",         "tester",       8),
        ("確認日",         "tested_date", 16),
        ("PC",             "status",       6),
        (display_col_name, image_col,     45),
    ]

    HEADER_ROW   = 20
    LEFT_MARGIN  = 1
    GRID_COL_W   = 2.2
    BASE_LINE_PX = 18
    CHAR_TO_PX   = 7.0

    with pd.ExcelWriter(out_path, engine="xlsxwriter") as writer:
        wb = writer.book
        ws = wb.add_worksheet("テスト項目")

        header_fmt = wb.add_format({
            "bold": True, "bg_color": "#C6EFCE",
            "border": 1, "align": "center", "valign": "vcenter"
        })
        cell_fmt = wb.add_format({
            "border": 1, "valign": "top", "text_wrap": True
        })

        total_grid_cols = LEFT_MARGIN + sum(w for _, _, w in SCHEMA) + 20
        bg_rows = HEADER_ROW + (len(df) * 4) + 80
        for c in range(total_grid_cols):
            ws.set_column(c, c, GRID_COL_W)
        for r in range(bg_rows):
            ws.set_row(r, 15)

        col_ptr = LEFT_MARGIN
        col_positions = []
        for label, _, width in SCHEMA:
            ws.merge_range(HEADER_ROW, col_ptr, HEADER_ROW, col_ptr + width - 1, label, header_fmt)
            col_positions.append((col_ptr, col_ptr + width - 1, width))
            col_ptr += width

        def text_height_px(text: Any, width_cols: int) -> int:
            s = "" if text is None else str(text)
            max_chars = max(1, int(width_cols * GRID_COL_W))
            lines = 1 if s == "" else sum(max(1, math.ceil(len(line) / max_chars)) for line in s.splitlines() or [""])
            return max(BASE_LINE_PX, lines * BASE_LINE_PX + 8)

        row_idx = HEADER_ROW + 1
        for i, rec in enumerate(df.to_dict("records"), start=1):
            mapped = {
                "row_no": i,
                "title": rec.get("title", ""),
                "edaban": "",
                "url": rec.get("url", ""),
                "check_text": rec.get("check_text") or CHECK_TEXT,
                "tester": rec.get("tester", ""),
                "tested_date": rec.get("tested_date", ""),
                "status": "OK" if str(rec.get("status", "")).upper() == "PASSED" else ("NG" if rec.get("status") else ""),
                image_col: rec.get(image_col, ""),
            }

            text_heights = []
            for (label, field, width), (c0, c1, wcols) in zip(SCHEMA, col_positions):
                if field in ("row_no", "edaban", "status", image_col):
                    continue
                text_heights.append(text_height_px(mapped.get(field, ""), wcols))
            text_h = max(text_heights) if text_heights else BASE_LINE_PX

            sc_c0, sc_c1, sc_wcols = col_positions[-1]
            target_w_px = sc_wcols * GRID_COL_W * CHAR_TO_PX
            img_path = str(mapped.get(image_col) or "")
            img_h = 0
            if img_path and os.path.exists(img_path):
                try:
                    with Image.open(img_path) as im:
                        wpx, hpx = im.size
                    scale = target_w_px / float(wpx) if wpx > 0 else 1.0
                    img_h = int(hpx * scale) + 10
                except Exception:
                    img_h = 0

            row_h_px = max(40, text_h, img_h)
            ws.set_row(row_idx, row_h_px * 0.75)

            for (label, field, width), (c0, c1, wcols) in zip(SCHEMA, col_positions):
                ws.merge_range(row_idx, c0, row_idx, c1,
                               "" if field == image_col else mapped.get(field, ""), cell_fmt)

            if img_path and os.path.exists(img_path):
                try:
                    with Image.open(img_path) as im:
                        wpx, hpx = im.size
                    scale = target_w_px / float(wpx) if wpx > 0 else 1.0
                    ws.insert_image(row_idx, sc_c0, img_path,
                                    {"x_scale": scale, "y_scale": scale, "x_offset": 1, "y_offset": 1})
                except Exception:
                    pass

            row_idx += 1

# ------------------------ Selenium bits ------------------------
def make_driver(headless: bool = False):
    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument("--allow-insecure-localhost")
    opts.add_argument("--window-size=1366,900")
    if headless:
        opts.add_argument("--headless=new")
    service = Service(ChromeDriverManager().install())
    drv = webdriver.Chrome(service=service, options=opts)
    return drv

def selenium_login(driver, login_url: str, admin_id: str, admin_id_name: str,
                   admin_pw: str, admin_pw_name: str, admin_submit_name: str):
    wait = WebDriverWait(driver, 20)
    driver.get(login_url)

    wait.until(EC.presence_of_element_located((By.NAME, admin_id_name))).clear()
    driver.find_element(By.NAME, admin_id_name).send_keys(admin_id)

    pw = wait.until(EC.presence_of_element_located((By.NAME, admin_pw_name)))
    pw.clear(); pw.send_keys(admin_pw)

    try:
        btn = wait.until(EC.element_to_be_clickable((By.NAME, admin_submit_name)))
    except Exception:
        btn = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "input[type='submit'], button[type='submit']")
        ))
    btn.click()

    wait.until(lambda d: d.current_url != login_url)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

def transfer_cookies_to_requests(sess: requests.Session, driver, base_url: str):
    host = urlsplit(base_url).hostname or "localhost"
    for c in driver.get_cookies():
        domain = (c.get("domain") or host).lstrip(".")
        sess.cookies.set(c["name"], c.get("value", ""), domain=domain, path=c.get("path") or "/")

def http_status(sess: requests.Session, url: str):
    try:
        r = sess.get(url, timeout=15, allow_redirects=True, verify=False)
        return r.status_code, (r.headers.get("Content-Type") or "").lower(), (r.text or "")
    except Exception:
        return None, None, ""

# ------------------------ Job runner ------------------------
def run_test_job(
    job_id: str,
    base_url: str,
    endpoints: List[str],
    test_type: str,
    login_url: str,
    login_id: str,
    login_id_name: str,
    login_pw: str,
    login_pw_name: str,
    login_submit_name: str,
    auto_fix: bool,
    project_root: str
):
    shots_dir = os.path.join(app.config["SHOT_ROOT"], f"job_{job_id}")
    os.makedirs(shots_dir, exist_ok=True)
    report_path = os.path.join(app.config["REPORT_FOLDER"], f"report_{job_id}.xlsx")

    with JOBS_LOCK:
        JOBS[job_id].update({
            "status": "running", "progress": 0, "total": len(endpoints),
            "report_path": None, "summary": {"passed": 0, "failed": 0}, "errors": {},
            "errors_by_file": {},
            "fixes": [],
            "project_root": project_root,
            "needs_confirmation": False,
            "targets": {},
        })

    driver = None
    aggregated_context_snippets = []

    try:
        driver = make_driver(headless=True)
        wait = WebDriverWait(driver, 20)

        sess = requests.Session()
        sess.verify = False
        sess.headers.update({"User-Agent": "dashboard-smoke/1.0"})

        if login_url and login_id and login_pw and login_id_name and login_pw_name:
            selenium_login(driver, login_url, login_id, login_id_name, login_pw, login_pw_name, login_submit_name or "send")
            transfer_cookies_to_requests(sess, driver, base_url)

        rows = []
        passed = failed = 0
        error_buckets: Dict[str, int] = {}
        error_files: Dict[str, int] = {}

        for idx, raw in enumerate(endpoints, start=1):
            url = normalize_url(raw, base_url, keep_query=True)
            status_code, ctype, body = http_status(sess, url)

            driver.get(url)
            try:
                wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            except Exception:
                pass

            title = (driver.title or "").strip()
            if not title:
                try:
                    title = driver.find_element(By.CSS_SELECTOR, "h1").text.strip()
                except Exception:
                    title = ""

            note = ""
            text_lower = (driver.page_source or "").lower()
            if test_type in ("smoke", "title"):
                if test_type == "smoke":
                    note = detect_error_note(text_lower)
                if not note and re.search(r"(404|not\s+found|ページが見つかりません)", title, re.I):
                    note = "Title indicates 404"

            if test_type in ("smoke", "status"):
                if ctype and ("text/html" not in ctype and "application/xhtml+xml" not in ctype):
                    note = f"Non-HTML content-type: {ctype}" + ((" | " + note) if note else "")
                if status_code and status_code >= 400:
                    note = f"HTTP {status_code}" + ((" | " + note) if note else "")

            # --- Collect PHP/TPL error file:line targets ---
            page_html = driver.page_source or body or ""
            targets = extract_php_targets(page_html)
            first_file_label = None
            if targets:
                aggregated_context_snippets.append(page_html[:4000])
                with JOBS_LOCK:
                    tgt = JOBS[job_id]["targets"]
                    for php_path, line in targets:
                        mapped = remap_host_path(php_path)
                        abs_path = mapped if os.path.isabs(mapped) else os.path.normpath(os.path.join(project_root, mapped))
                        rec = tgt.get(abs_path) or {"lines": set(), "count": 0}
                        rec["lines"].add(int(line))
                        rec["count"] += 1
                        tgt[abs_path] = rec

                        label = f"{os.path.basename(abs_path)}:{int(line)}"
                        if first_file_label is None:
                            first_file_label = label
                        error_files[label] = error_files.get(label, 0) + 1

                    JOBS[job_id]["needs_confirmation"] = True

            if first_file_label:
                note = f"{note} | {first_file_label}" if note else first_file_label

            shot_path = url_to_shot(job_id, url)
            fullpage_screenshot(driver, shot_path)

            status = "PASSED" if not note else "FAILED"
            if status == "PASSED":
                passed += 1
            else:
                failed += 1
                error_buckets[note or "undefined"] = error_buckets.get(note or "undefined", 0) + 1

            rows.append({
                "url": url, "title": title, "status": status, "note": note or "",
                "tested_date": now_str(), "tester": TESTER, "screenshot_path": shot_path,
                "http_status": status_code
            })

            with JOBS_LOCK:
                JOBS[job_id]["progress"] = idx
                JOBS[job_id]["summary"] = {"passed": passed, "failed": failed}
                JOBS[job_id]["errors"]  = error_buckets
                JOBS[job_id]["errors_by_file"] = error_files

        df = pd.DataFrame(rows)
        write_with_images_fit(df, report_path, image_col="screenshot_path", display_col_name="スクリーンショット")

        with JOBS_LOCK:
            JOBS[job_id]["status"] = "done"
            JOBS[job_id]["report_path"] = report_path
            JOBS[job_id]["context_html"] = "\n\n".join(aggregated_context_snippets[-5:])

    except Exception as e:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error_msg"] = f"{type(e).__name__}: {e}"
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass

# ------------------------ Routes ------------------------
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route('/ai/health', methods=['GET'])
def health_check():
    res = ai_health()
    return jsonify(res)

@app.route("/run-test", methods=["POST"])
def run_test():
    base_url  = request.form.get("base_url", "").strip()
    test_type = (request.form.get("test_type") or "smoke").strip().lower()

    login_url = request.form.get("login_url", "").strip()
    login_id  = request.form.get("login_id", "").strip()
    login_id_name = request.form.get("login_id_name", "").strip()
    login_pw  = request.form.get("login_pw", "").strip()
    login_pw_name = request.form.get("login_pw_name", "").strip()
    login_submit_name = request.form.get("login_submit_name", "").strip()

    project_root = request.form.get("project_root", "").strip()
    auto_fix = request.form.get("auto_fix") == '1'

    endpoints_text = request.form.get("endpoints_text", "")
    endpoints = [ln.strip() for ln in endpoints_text.splitlines() if ln.strip()]

    excel_file = request.files.get("excel_file")
    if excel_file and excel_file.filename:
        if not excel_file.filename.lower().endswith(".xlsx"):
            return jsonify({"ok": False, "error": "Only .xlsx is accepted"}), 400
        df_upload = pd.read_excel(excel_file)
        if "url" not in df_upload.columns:
            return jsonify({"ok": False, "error": "Excel must have a 'url' column"}), 400
        endpoints_from_xlsx = [str(u).strip() for u in df_upload["url"].tolist() if (isinstance(u, str) and u.strip()) or pd.notna(u)]
        endpoints.extend(endpoints_from_xlsx)

    normed = []
    seen = set()
    for u in endpoints:
        n = normalize_url(str(u), base_url, keep_query=True)
        if n and n not in seen:
            seen.add(n)
            normed.append(n)

    if not base_url:
        return jsonify({"ok": False, "error": "base_url is required"}), 400
    if not normed:
        return jsonify({"ok": False, "error": "No endpoints provided"}), 400

    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "queued", "progress": 0, "total": len(normed), "created_at": now_str(),
            "project_root": project_root, "auto_fix": auto_fix
        }

    t = threading.Thread(
        target=run_test_job,
        args=(job_id, base_url, normed, test_type,
              login_url, login_id, login_id_name, login_pw, login_pw_name, login_submit_name,
              auto_fix, project_root),
        daemon=True
    )
    t.start()

    return jsonify({"ok": True, "job_id": job_id})

@app.route("/job/<job_id>/status", methods=["GET"])
def job_status(job_id):
    with JOBS_LOCK:
        data = JOBS.get(job_id)
    if not data:
        return jsonify({"ok": False, "error": "job not found"}), 404

    resp = dict(data)
    resp.pop("targets", None)  # remove set-heavy structure from status payload

    def _safe(o):
        if isinstance(o, set):
            return sorted(list(o))
        if isinstance(o, dict):
            return {k: _safe(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_safe(x) for x in o]
        return o

    resp = _safe(resp)

    if data.get("report_path"):
        resp["download_url"] = f"/job/{job_id}/download"
    return jsonify({"ok": True, "job": resp})

@app.route("/job/<job_id>/download", methods=["GET"])
def job_download(job_id):
    with JOBS_LOCK:
        data = JOBS.get(job_id)
    if not data or data.get("status") != "done" or not data.get("report_path"):
        return jsonify({"ok": False, "error": "report not ready"}), 404
    path = data["report_path"]
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))

@app.route("/job/<job_id>/targets", methods=["GET"])
def job_targets(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "job not found"}), 404

    targets = []
    for fpath, rec in (job.get("targets") or {}).items():
        targets.append({
            "file": fpath,
            "lines": sorted(list(rec["lines"])) if isinstance(rec.get("lines"), set) else (rec.get("lines") or []),
            "count": int(rec.get("count") or 0),
            "exists": os.path.exists(fpath)
        })
    return jsonify({"ok": True, "targets": targets, "needs_confirmation": bool(job.get("needs_confirmation"))})

@app.route("/job/<job_id>/fix", methods=["POST"])
def job_fix(job_id):
    data = request.get_json(force=True, silent=True) or {}
    items = data.get("items") or []   # [{file, lines:[...] }]
    options = data.get("options") or {}  # e.g., {"dynprops":"off|declare|attribute"}
    if not options.get("dynprops"):
        options["dynprops"] = "declare"   

    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "job not found"}), 404

    project_root = job.get("project_root") or ""
    context_html = job.get("context_html") or ""
    allowed = set((job.get("targets") or {}).keys())
    filtered_items = [it for it in items if (it.get("file") in allowed)]

    if not filtered_items:
        return jsonify({"ok": False, "error": "no valid items"}), 400

    results = fix_selected(project_root, filtered_items, context_html, options=options)

    with JOBS_LOCK:
        (job.get("fixes") or []).extend(results)
        job["needs_confirmation"] = False
    return jsonify({"ok": True, "results": results})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5051"))
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
