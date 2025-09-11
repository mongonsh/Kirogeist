import os, re, io, uuid, time, json, hashlib, threading, warnings, datetime as dt
from typing import List, Dict, Any
from urllib.parse import urljoin, urlsplit, urldefrag, parse_qsl, urlencode, urlunsplit
from openai import OpenAI

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

# --- our fixer (rules + optional AI) ---
from fixer import fix_files_for_error_html

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
    # Japanese
    r"ページが見つかりません", r"指定されたページは見つかりません",
    r"お探しのページは見つかりませんでした", r"エラーが発生", r"メンテナンス中", r"アクセス(が)?拒否",
]
WEAK_ERROR_PATTERNS = [r"\bwarning\b", r"\bnotice\b", r"whoops", r"oops"]
ERROR_RE_STRONG = re.compile("|".join(STRONG_ERROR_PATTERNS), re.I | re.S)
ERROR_RE_WEAK   = re.compile("|".join(WEAK_ERROR_PATTERNS), re.I | re.S)

# ai section

# Read API key from env
client = OpenAI(api_key='')

# default model
DEFAULT_MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini")

def chat(messages, model: str = None, temperature: float = 0.2, max_tokens: int = 2048) -> str:
    m = model or DEFAULT_MODEL
    resp = client.chat.completions.create(
        model=m,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()

def ai_health(model: str = None) -> dict:
    """Return {"ok", "model", "latency_ms", "error"}"""
    m = model or DEFAULT_MODEL
    t0 = time.time()
    try:
        client.chat.completions.create(
            model=m,
            messages=[{"role":"system","content":"healthcheck"},{"role":"user","content":"ping"}],
            temperature=0.0,
            max_tokens=1,
        )
        return {"ok": True, "model": m, "latency_ms": int((time.time()-t0)*1000), "error": None}
    except Exception as e:
        return {"ok": False, "model": m, "latency_ms": int((time.time()-t0)*1000), "error": f"{type(e).__name__}: {e}"}

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

# ------------------------ Japanese-grid writer ------------------------
def write_with_images_fit(
    df: pd.DataFrame,
    out_path: str,
    image_col: str = "screenshot_path",
    display_col_name: str = "スクリーンショット",
    col_width_chars: float = 0.0  # kept for API compatibility (unused here)
):
    """
    Japanese grid look:
      - tiny background grid
      - merge only the table area horizontally
      - row height = max(text height, scaled screenshot height)
      - 「確認する内容」 is populated from df['check_text'] (or CHECK_TEXT)
      - screenshots preserved
    """
    import xlsxwriter, math, os
    from typing import Any
    from PIL import Image

    # ----- TABLE SCHEMA (merged horizontal blocks, widths in micro-grid columns) -----
    SCHEMA = [
        ("番号",           "row_no",       4),
        ("テスト確認項目",  "title",       36),
        ("枝番",           "edaban",       5),
        ("実施方法",       "url",         28),
        ("確認する内容",    "check_text",  48),  # ← use check_text instead of note
        ("確認者",         "tester",       8),
        ("確認日",         "tested_date", 16),
        ("PC",            "status",       6),
        (display_col_name, image_col,     45),
    ]

    HEADER_ROW   = 20
    LEFT_MARGIN  = 1
    GRID_COL_W   = 2.2   # width of each micro column
    BASE_LINE_PX = 18    # approx height per wrapped line
    CHAR_TO_PX   = 7.0

    with pd.ExcelWriter(out_path, engine="xlsxwriter") as writer:
        wb = writer.book
        ws = wb.add_worksheet("テスト項目")

        # formats
        header_fmt = wb.add_format({
            "bold": True, "bg_color": "#C6EFCE",
            "border": 1, "align": "center", "valign": "vcenter"
        })
        cell_fmt = wb.add_format({
            "border": 1, "valign": "top", "text_wrap": True
        })

        # background grid (outside table is tiny cells)
        total_grid_cols = LEFT_MARGIN + sum(w for _, _, w in SCHEMA) + 20
        bg_rows = HEADER_ROW + (len(df) * 4) + 80
        for c in range(total_grid_cols):
            ws.set_column(c, c, GRID_COL_W)
        for r in range(bg_rows):
            ws.set_row(r, 15)

        # header (merge only table area)
        col_ptr = LEFT_MARGIN
        col_positions = []
        for label, _, width in SCHEMA:
            ws.merge_range(HEADER_ROW, col_ptr, HEADER_ROW, col_ptr + width - 1, label, header_fmt)
            col_positions.append((col_ptr, col_ptr + width - 1, width))
            col_ptr += width

        # helper: estimate text height
        def text_height_px(text: Any, width_cols: int) -> int:
            s = "" if text is None else str(text)
            # rough chars that fit per line for this merged width
            max_chars = max(1, int(width_cols * GRID_COL_W))
            lines = 1 if s == "" else sum(max(1, math.ceil(len(line) / max_chars)) for line in s.splitlines() or [""])
            return max(BASE_LINE_PX, lines * BASE_LINE_PX + 8)

        # write records
        row_idx = HEADER_ROW + 1
        for i, rec in enumerate(df.to_dict("records"), start=1):
            mapped = {
                "row_no": i,
                "title": rec.get("title", ""),
                "edaban": "",
                "url": rec.get("url", ""),
                # ← this is the IMPORTANT change
                "check_text": rec.get("check_text") or CHECK_TEXT,
                "tester": rec.get("tester", ""),
                "tested_date": rec.get("tested_date", ""),
                "status": "OK" if str(rec.get("status", "")).upper() == "PASSED" else ("NG" if rec.get("status") else ""),
                image_col: rec.get(image_col, ""),
            }

            # text height (exclude row_no/edaban/status/image)
            text_heights = []
            for (label, field, width), (c0, c1, wcols) in zip(SCHEMA, col_positions):
                if field in ("row_no", "edaban", "status", image_col):
                    continue
                text_heights.append(text_height_px(mapped.get(field, ""), wcols))
            text_h = max(text_heights) if text_heights else BASE_LINE_PX

            # image height
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

            # merge and write each block
            for (label, field, width), (c0, c1, wcols) in zip(SCHEMA, col_positions):
                ws.merge_range(row_idx, c0, row_idx, c1,
                               "" if field == image_col else mapped.get(field, ""), cell_fmt)

            # then place the image on top of the merged screenshot block
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
def make_driver(headless: bool = True):
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
            "fixes": []
        })

    driver = None
    try:
        driver = make_driver(headless=True)
        wait = WebDriverWait(driver, 20)

        sess = requests.Session()
        sess.verify = False
        sess.headers.update({"User-Agent": "dashboard-smoke/1.0"})

        # login optional (kept as-is)
        if login_url and login_id and login_pw and login_id_name and login_pw_name:
            selenium_login(driver, login_url, login_id, login_id_name, login_pw, login_pw_name, login_submit_name or "send")
            transfer_cookies_to_requests(sess, driver, base_url)

        rows = []
        passed = failed = 0
        error_buckets: Dict[str, int] = {}

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

            # optional fixes
            if auto_fix:
                print('yes there has to be fixed.')
                page_html = driver.page_source or body or ""
                if project_root:
                    fix_records = fix_files_for_error_html(project_root, page_html)
                    with JOBS_LOCK:
                        JOBS[job_id]["fixes"].extend(fix_records)

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

        df = pd.DataFrame(rows)

        # === Japanese grid + merged content area ===
        write_with_images_fit(
            df,
            report_path,
            image_col="screenshot_path",
            display_col_name="スクリーンショット"  # label for the screenshot header
        )

        with JOBS_LOCK:
            JOBS[job_id]["status"] = "done"
            JOBS[job_id]["report_path"] = report_path

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
    return render_template("index_v1.html")

@app.route('/ai/health', methods=['GET'])
def health_check():
    res = ai_health()
    print('result:', res)
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
    print('auto fix:', request.form.get("auto_fix"))
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
        JOBS[job_id] = {"status": "queued", "progress": 0, "total": len(normed), "created_at": now_str()}
    print('auto fix is:', auto_fix)
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5051"))
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
