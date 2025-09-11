# agents.py
import os, re, time, io, json, uuid, hashlib, subprocess, shutil, warnings, difflib, tempfile
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

import pandas as pd
import requests
import yaml
from PIL import Image
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


options = Options()
options.add_argument("--ignore-certificate-errors")
options.add_argument("--allow-insecure-localhost")
warnings.filterwarnings("ignore")

# ---------------- Utilities ----------------
def hashname(s: str, ext=".png"):
    h = hashlib.md5(s.encode("utf-8")).hexdigest()[:12]
    os.makedirs("./shots", exist_ok=True)
    return os.path.join("./shots", f"{h}{ext}")

def safe_status(url: str, timeout=10):
    try: return requests.get(url, timeout=timeout, verify=False).status_code
    except: return None

def lower(s: str) -> str:
    try: return s.lower()
    except: return s

# ---------------- Precise PHP error detector ----------------
PHP_ERROR_PATTERNS = [
    re.compile(r"(?:^|\b)(Fatal error|Parse error|Warning|Notice|Deprecated)\b", re.I),
    re.compile(r" in (/.+?\.php)\s+on line\s+(\d+)", re.I),
    re.compile(r"<b>(Fatal error|Warning|Notice|Deprecated)</b>:", re.I),
    re.compile(r"session save path cannot be changed when a session is active", re.I),
]
EXCLUDE_CSS_CLASSES = ("example", "docs", "documentation", "help", "guide", "cheatsheet")

def _visible(el):
    try: return el.is_displayed()
    except: return True

def extract_php_error(html: str, driver=None) -> Tuple[bool, str, str]:
    if not html: return False, "", ""
    if not PHP_ERROR_PATTERNS[0].search(html):  # quick reject
        return False, "", ""

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]): tag.decompose()
    for tag in soup(["pre", "code"]):
        cls = " ".join(tag.get("class", [])).lower()
        if any(c in cls for c in EXCLUDE_CSS_CLASSES): tag.decompose()

    CANDS = [
        "//*[self::div or self::p or self::span or self::pre][contains(., 'Fatal error')]",
        "//*[self::div or self::p or self::span or self::pre][contains(., 'Warning')]",
        "//*[self::div or self::p or self::span or self::pre][contains(., 'Notice')]",
        "//*[self::div or self::p or self::span or self::pre][contains(., 'Deprecated')]",
    ]
    texts = []
    if driver:
        for xp in CANDS:
            try:
                for el in driver.find_elements(By.XPATH, xp):
                    if not _visible(el): continue
                    cls = (el.get_attribute("class") or "").lower()
                    if any(k in cls for k in EXCLUDE_CSS_CLASSES): continue
                    t = (el.text or "").strip()
                    if t: texts.append(t)
            except: pass

    def strong(txt: str) -> Tuple[bool, str]:
        if not txt: return (False, "")
        if PHP_ERROR_PATTERNS[2].search(txt): return (True, txt)
        if PHP_ERROR_PATTERNS[0].search(txt) and PHP_ERROR_PATTERNS[1].search(txt): return (True, txt)
        if PHP_ERROR_PATTERNS[3].search(txt): return (True, txt)
        return (False, "")

    for t in texts:
        ok, ev = strong(t)
        if ok:
            m = PHP_ERROR_PATTERNS[1].search(ev)
            fp = m.group(1) if m else ""
            return True, ev[:500], fp

    full = soup.get_text(" ", strip=True)
    ok, ev = strong(full)
    if ok:
        m = PHP_ERROR_PATTERNS[1].search(ev)
        fp = m.group(1) if m else ""
        return True, ev[:500], fp
    return False, "", ""

# ---------------- Collector ----------------
class EndpointCollector:
    def __init__(self, base_url: str, seeds: List[str]):
        self.base_url = base_url
        self.seeds = seeds or []

    def collect(self) -> List[Dict]:
        return [dict(url=u, method="GET", source="manual") for u in self.seeds]

# ---------------- Checker (Selenium) ----------------
class Checker:
    def __init__(self):
        opts = Options()
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
        self.wait = WebDriverWait(self.driver, 15)

    def login_if_needed(self, login_url=None, login_id=None, login_pw=None,
                        sel_id="input[name='loginid']", sel_pw="input[name='password']", sel_send="input[name='send']"):
        if not (login_url and login_id and login_pw): return
        self.driver.get(login_url)
        try:
            id_el = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel_id)))
            pw_el = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel_pw)))
            id_el.clear(); id_el.send_keys(login_id)
            pw_el.clear(); pw_el.send_keys(login_pw)
            self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel_send))).click()
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        except Exception as e:
            print("[login] skip/failed:", e)

    def check_one(self, ep: Dict) -> Dict:
        status = safe_status(ep["url"])
        title, shot = "", None
        try:
            self.driver.set_window_size(1366, 900)
            self.driver.get(ep["url"])
            try: self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            except: pass

            title = self.driver.title or ""
            html = self.driver.page_source or ""
            is_err, snippet, file_path = extract_php_error(html, driver=self.driver)

            shot = hashname(ep["url"])
            self.driver.save_screenshot(shot)

            return dict(url=ep["url"], title=title, is_error=is_err, error_snippet=snippet,
                        screenshot=shot, http_status=status, file_path=file_path)
        except Exception as e:
            return dict(url=ep["url"], title=title, is_error=True,
                        error_snippet=f"checker exception: {e}", screenshot=shot,
                        http_status=status, file_path="")

    def close(self):
        try: self.driver.quit()
        except: pass

# ---------------- Fixer (rule-based) ----------------
class Fixer:
    def __init__(self, project_root: str, pattern_file: str):
        self.root = project_root
        self.rules = []
        if os.path.exists(pattern_file):
            self.rules = yaml.safe_load(open(pattern_file, "r", encoding="utf-8"))["rules"]

    def _extract_stack_file(self, page_html_lower: str) -> Optional[str]:
        m = re.search(r"(/home/[^<\s]+?\.(php|tpl))", page_html_lower)
        if m:
            p = m.group(1)
            if os.path.exists(p): return p
            # naive mapping: if absolute path differs, try join with project root
            rp = p[1:] if p.startswith("/") else p
            cand = os.path.join(self.root, rp)
            if os.path.exists(cand): return cand
        return None

    def _iter_php_files(self):
        for root, _, files in os.walk(self.root):
            for fn in files:
                if fn.endswith((".php", ".phtml", ".tpl")):
                    yield os.path.join(root, fn)

    def _apply_rule_to_file(self, path: str, rule: Dict) -> Tuple[bool, str]:
        try:
            src = open(path, "r", encoding="utf-8", errors="ignore").read()
            new = re.sub(rule["search"], rule["replace"], src, flags=re.I)
            if new != src:
                shutil.copyfile(path, path + ".bak")
                with open(path, "w", encoding="utf-8") as f: f.write(new)
                # quick lint
                ok = self._php_lint_file(path)
                if not ok:
                    # revert on lint failure
                    shutil.copyfile(path + ".bak", path)
                    return False, "lint failed; reverted"
                return True, f"patched: {rule['id']}"
            return False, "no change"
        except Exception as e:
            return False, f"error: {e}"

    def _php_lint_file(self, path: str) -> bool:
        try:
            p = subprocess.run(["php", "-l", path], capture_output=True, text=True, timeout=20)
            return p.returncode == 0
        except Exception:
            return True  # best effort

    def _wrap_array_access_with_coalesce(self, src: str, key: str) -> str:
        # 1) Superglobals $_GET/$_POST/$_REQUEST/$_COOKIE['key']  ->  (... ?? null)
        pat_super = re.compile(
            r"(\$_(?:GET|POST|REQUEST|COOKIE)\[['\"]" + re.escape(key) + r"['\"]\])(?!\s*\?\?)",
            flags=re.I
        )
        src2 = pat_super.sub(r"(\1 ?? null)", src)

        # 2) Any variable $var['key']  ->  (... ?? null)
        pat_any = re.compile(
            r"(\$[A-Za-z_][A-Za-z0-9_]*\[['\"]" + re.escape(key) + r"['\"]\])(?!\s*\?\?)"
        )
        src3 = pat_any.sub(r"(\1 ?? null)", src2)
        return src3

    def _apply_key_fix_to_file(self, file_path: str, key: str) -> tuple[bool, str]:
        if not file_path or not os.path.exists(file_path):
            return False, f"file not found: {file_path}"
        src = open(file_path, "r", encoding="utf-8", errors="ignore").read()
        new = self._wrap_array_access_with_coalesce(src, key)
        if new != src:
            shutil.copyfile(file_path, file_path + ".bak")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new)
            # lint only PHP-like files
            if file_path.endswith((".php", ".phtml", ".tpl")):
                if not self._php_lint_file(file_path):
                    shutil.copyfile(file_path + ".bak", file_path)
                    return False, "lint failed; reverted"
            return True, f"coalesced '{key}' in {os.path.basename(file_path)}"
        return False, "no change"

    # --- REPLACE try_fix with this version ----------------------------------
    def try_fix(self, page_html_lower: str, error_snippet: str = "", file_hint: str | None = None):
        """
        1) If error_snippet says 'Undefined array key "<key>"', coalesce that key in the hinted file.
        2) Otherwise fall back to rules from patterns.yaml.
        """
        # Step 1: key-targeted fix
        m = re.search(r'Undefined array key ["\']([^"\']+)["\']', error_snippet or "", re.I)
        if m:
            key = m.group(1)
            target = file_hint or self._extract_stack_file(page_html_lower)
            ok, why = self._apply_key_fix_to_file(target, key) if target else (False, "no target file")
            if ok:
                return True, f"coalesce:{key}", why

        # Step 2: rule-based (existing behavior)
        if not self.rules:
            return (False, None, "no rules")
        candidates = [r for r in self.rules if r.get("match") and (r["match"].lower() in (error_snippet or "").lower())]
        if not candidates:
            candidates = self.rules

        targets = []
        if file_hint and os.path.exists(file_hint):
            targets.append(file_hint)
        else:
            hint = self._extract_stack_file(page_html_lower)
            if hint: targets.append(hint)

        for rule in candidates:
            if targets:
                for fp in targets:
                    ok, why = self._apply_rule_to_file(fp, rule)
                    if ok: return True, rule["id"], f"{why} @ {fp} // {rule.get('note','')}"
            for fp in self._iter_php_files():
                ok, _ = self._apply_rule_to_file(fp, rule)
                if ok:
                    return True, rule["id"], f"patched {fp} // {rule.get('note','')}"
        return False, None, "no matching edits"

# ---------------- AI Advisor (optional) ----------------
AI_MIGRATION_PROMPT = """
You are a senior QA tester and PHP 8.3 migration assistant.
Goal: fix runtime PHP errors/warnings surfaced in a web page WITHOUT changing app behavior.

Constraints:
- Small, surgical, idempotent edits only. Prefer modern PHP 8 constructs (??, ??=, nullsafe).
- No dependency or broad refactors. Do not change I/O or DB unless necessary for the error.
- Output STRICT JSON ONLY (no prose):
{
  "confidence": 0..1,
  "explanation": "...",
  "patches": [
    {"path": "/abs/or/rel/file.php", "unified_diff": "valid unified diff against current file contents"}
  ]
}
If unsure, return an empty patches array with explanation.
"""

class AdvisorAI:
    def __init__(self, fixer: Fixer, model: str = "gpt-4o-mini"):
        self.fixer = fixer
        self.model = model
        self.enabled = bool()

    def _read_context(self, file_path: str, max_bytes=120_000):
        if not file_path or not os.path.exists(file_path): return ""
        return open(file_path, "r", encoding="utf-8", errors="ignore").read()[:max_bytes]

    def call_ai(self, error_snippet: str, file_path: str) -> Dict:
        if not self.enabled:
            return {"confidence": 0.0, "explanation": "AI disabled", "patches": []}
        import openai
        ctx = self._read_context(file_path)
        messages = [
            {"role": "system", "content": AI_MIGRATION_PROMPT},
            {"role": "user", "content": json.dumps({"error_snippet": error_snippet, "file_path": file_path, "code_context": ctx}, ensure_ascii=False)}
        ]
        resp = openai.ChatCompletion.create(model=self.model, messages=messages)
        txt = resp["choices"][0]["message"]["content"]
        try:
            return json.loads(txt)
        except Exception:
            return {"confidence": 0.0, "explanation": "Invalid JSON from model.", "patches": []}

    def _apply_with_patch_tool(self, path: str, unified_diff: str) -> Tuple[bool, str]:
        if not path or not os.path.exists(path):
            return False, f"target not found: {path}"
        if shutil.which("patch"):
            with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
                f.write(unified_diff)
                diffpath = f.name
            pr = subprocess.run(["patch", "-p0", path, diffpath], capture_output=True, text=True)
            os.unlink(diffpath)
            if pr.returncode == 0:
                return True, "patched via patch(1)"
            return False, f"patch failed: {pr.stderr[:200]}"
        return False, "patch tool not available"

    def propose_and_fix(self, page_html_lower: str, error_snippet: str, file_hint: Optional[str]) -> Tuple[bool, str, str]:
        # 1) Rule-based
        fixed, rule_id, note = self.fixer.try_fix(page_html_lower, error_snippet, file_hint)
        if fixed: return True, f"rule:{rule_id}", note

        # 2) AI
        file_path = file_hint or self.fixer._extract_stack_file(page_html_lower)
        ai = self.call_ai(error_snippet, file_path or "")
        patches = ai.get("patches") or []
        if not patches:
            return False, "ai-none", ai.get("explanation", "no patches")

        applied = []
        for p in patches:
            tgt = p.get("path") or file_path
            diff = p.get("unified_diff") or ""
            ok, why = self._apply_with_patch_tool(tgt, diff)
            applied.append(f"{tgt}: {why}")
        if any(s.startswith("patched") for s in applied):
            return True, "ai", " ; ".join(applied)
        return False, "ai-failed", " ; ".join(applied)

# ---------------- Reporter (Excel with screenshots) ----------------
def write_with_images_fit(df: pd.DataFrame, out_path: str, image_col="screenshot", display_col_name="スクリーンショット"):
    out_df = df.copy()
    out_df[display_col_name] = ""
    with pd.ExcelWriter(out_path, engine="xlsxwriter") as writer:
        out_df.to_excel(writer, index=False, sheet_name="Report")
        ws = writer.sheets["Report"]

        header_fmt = writer.book.add_format({"bold": True, "bg_color": "#B7E1CD", "border": 1})
        for c, name in enumerate(out_df.columns):
            ws.write(0, c, name, header_fmt)

        cols = list(out_df.columns)
        img_col_idx = cols.index(display_col_name)
        # widths
        def setw(name, width):
            if name in cols:
                i = cols.index(name); ws.set_column(i, i, width)
        setw("url", 60)
        setw("タイトル", 40) if "タイトル" in cols else None
        ws.set_column(img_col_idx, img_col_idx, 45)

        target_col_width_px = 45*7
        for r, path in enumerate(out_df[image_col].tolist(), start=1):
            if isinstance(path, str) and os.path.exists(path):
                with Image.open(path) as img: w, h = img.size
                scale = target_col_width_px / float(w) if w else 1.0
                ws.set_row(r, h*scale*0.75)
                ws.insert_image(r, img_col_idx, path, {"x_scale": scale, "y_scale": scale})
            else:
                ws.set_row(r, 18)
