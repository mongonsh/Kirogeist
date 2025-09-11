# fixer.py
import os, re, shutil, json
from typing import Dict, Any, List, Tuple
import yaml
from openai import OpenAI

# ============== AI ============
_AI_MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini")
_client = None
def _get_client():
    global _client
    if _client is None:
        _client = OpenAI()  # OPENAI_API_KEY from env
    return _client

def chat(messages, model: str = None, temperature: float = 0.2, max_tokens: int = 2048) -> str:
    m = model or _AI_MODEL
    resp = _get_client().chat.completions.create(
        model=m, messages=messages, temperature=temperature, max_tokens=max_tokens
    )
    return resp.choices[0].message.content.strip()

PATTERN_FILE = os.environ.get("PHP_FIX_PATTERNS") or "./patterns.yaml"

__all__ = ["extract_php_targets", "fix_selected", "fix_errors", "remap_host_path"]

# ============== PATH REMAP (docker → host) ============
def _load_path_maps():
    try:
        maps = json.loads(os.environ.get("PATH_MAPS", "[]"))
    except Exception:
        maps = []
    if not maps:
        maps = [{
            "from": "/home/www-virtual/kangoiryo.jp",
            "to": r"D:\XAMPP\htdocs\kangoiryo.jp\branches\mungunshagai"
        }]
    maps = [m for m in maps if isinstance(m, dict) and m.get("from") and m.get("to")]
    maps.sort(key=lambda m: len(str(m["from"])), reverse=True)
    return maps

_PATH_MAPS = _load_path_maps()

def remap_host_path(path_in: str) -> str:
    if not path_in: return path_in
    u = str(path_in).replace("\\", "/")
    for m in _PATH_MAPS:
        src = str(m["from"]).rstrip("/").replace("\\", "/")
        if u.startswith(src):
            tail = u[len(src):]
            dst = str(m["to"]).rstrip("\\/")
            return os.path.normpath(dst + tail.replace("/", os.sep))
    return os.path.normpath(path_in)

# ============== TARGET EXTRACTION (.php/.tpl) ============
_EXT = r"(?:php|phtml|tpl|inc)"
_PATH_PATTERNS = [
    rf"in\s*(?:<b>\s*)?(?P<path>[^<>\r\n\"']+?\.{_EXT})(?:\s*</b>)?\s*on\s*line(?:[^0-9]{{0,80}})?(?P<line>\d+)",
    rf"(?:in|at)\s+(?P<path>(?:/|[A-Za-z]:\\)[^:<>\r\n\"']+?\.{_EXT})\s+(?:on\s*)?line(?:[^0-9]{{0,80}})?(?P<line>\d+)",
]
_PATH_RES = [re.compile(p, re.IGNORECASE | re.S) for p in _PATH_PATTERNS]

def extract_php_targets(html_or_text: str) -> List[Tuple[str, int]]:
    out: List[Tuple[str, int]] = []
    if not html_or_text: return out
    s = str(html_or_text)
    s = s.replace("&quot;", '"').replace("&lt;br /&gt;", "<br />").replace("&lt;br/&gt;", "<br/>")
    for rx in _PATH_RES:
        for m in rx.finditer(s):
            try:
                p = (m.group("path") or "").strip()
                ln = int(m.group("line"))
                if p: out.append((p, ln))
            except Exception:
                pass
    seen=set(); uniq=[]
    for p, ln in out:
        key=(os.path.normpath(p), ln)
        if key not in seen:
            seen.add(key); uniq.append((p, ln))
    return uniq

# ============== RULES LOADER + SAFE REPLACE ============
def _sanitize_replacement(template: str) -> str:
    if template is None: return ""
    s = str(template)
    # keep \1 \2 \g<name> and \\ ; escape other lone backslashes → avoid "bad escape \A"
    return re.sub(r'\\(?![0-9]|g<|\\)', r'\\\\', s)

def load_rules() -> List[Dict[str, Any]]:
    if not os.path.exists(PATTERN_FILE): return []
    with open(PATTERN_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    rules = data.get("rules") or []
    out: List[Dict[str, Any]] = []
    for r in rules:
        if not isinstance(r, dict): continue
        rid = str(r.get("id") or "rule")
        search = r.get("search")
        replace = r.get("replace", "")
        note = r.get("note", "")
        if not isinstance(search, str): continue
        out.append({"id": rid, "search": search, "replace": replace, "note": note})
    return out

# ============== STYLE INFERENCE ============
def _infer_eol(code: str) -> str:
    crlf = code.count("\r\n"); lf = code.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"

def _infer_indent(code: str) -> str:
    tab_lines = len(re.findall(r"^\t+\S", code, re.M))
    sp_leads = [len(m.group(1)) for m in re.finditer(r"^( +)\S", code, re.M)]
    if tab_lines > len(sp_leads): return "\t"
    from collections import Counter
    steps = Counter(); prev = None
    for m in re.finditer(r"^( +)\S", code, re.M):
        n = len(m.group(1))
        if prev is not None and n > prev: steps[n - prev] += 1
        prev = n
    size = 4
    if steps:
        size = max(steps, key=steps.get)
        if size not in (2,3,4,8): size = 4 if size >= 4 else 2
    return " " * size

def _infer_brace_style(code: str) -> str:
    same = len(re.findall(r"\)\s*\{", code))
    nextl = len(re.findall(r"\)\s*\r?\n\s*\{", code))
    return "same_line" if same >= nextl else "next_line"

def _count_strings(code: str):  # rough signals
    singles = len(re.findall(r"'[^'\n]*'", code))
    doubles = len(re.findall(r"\"[^\"\n]*\"", code))
    return singles, doubles

def _infer_quotes(code: str) -> str:
    s, d = _count_strings(code); return "single" if s >= d else "double"

def _infer_array_syntax(code: str) -> str:
    short = len(re.findall(r"\[[^\]]*\]", code))
    longf = len(re.findall(r"\barray\s*\(", code))
    return "short" if short >= longf else "long"

def _infer_concat_spacing(code: str) -> bool:
    with_space = len(re.findall(r"\s\.\s", code))
    tight = len(re.findall(r"[^\s]\.[^\s]", code))
    return with_space >= tight

def _infer_ctrl_spacing(code: str) -> str:
    spaced = len(re.findall(r"\b(?:if|for|foreach|while|switch)\s+\(", code))
    tight  = len(re.findall(r"\b(?:if|for|foreach|while|switch)\(", code)) - spaced
    return "spaced" if spaced >= tight else "tight"

def _infer_short_echo(code: str) -> bool:
    return code.count("<?= ") + code.count("<?=\t") > code.count("echo ")

def infer_style(code: str) -> Dict[str, Any]:
    return {
        "eol": _infer_eol(code),
        "indent": _infer_indent(code),
        "brace": _infer_brace_style(code),
        "quotes": _infer_quotes(code),
        "array": _infer_array_syntax(code),
        "concat_spaced": _infer_concat_spacing(code),
        "ctrl_spacing": _infer_ctrl_spacing(code),
        "short_echo": _infer_short_echo(code),
    }

def style_hint(style: Dict[str, Any]) -> str:
    ind = "\\t (tabs)" if style["indent"] == "\t" else f"{len(style['indent'])} spaces"
    array = "[] short arrays" if style["array"] == "short" else "array() long arrays"
    quotes = "single quotes" if style["quotes"] == "single" else "double quotes"
    brace = "brace on same line" if style["brace"] == "same_line" else "brace on next line"
    echo = "prefer short echo <?= ?>" if style["short_echo"] else "prefer echo statements"
    dot = "spaces around dot" if style["concat_spaced"] else "no spaces around dot"
    ctrl = "keyword + space before (" if style["ctrl_spacing"] == "spaced" else "no space after keyword"
    eol = "CRLF" if style["eol"] == "\r\n" else "LF"
    return (
        f"- Indentation: {ind}\n"
        f"- Line endings: {eol}\n"
        f"- Braces: {brace}\n"
        f"- Quotes: {quotes}\n"
        f"- Arrays: {array}\n"
        f"- Echo style: {echo}\n"
        f"- Concatenation: {dot}\n"
        f"- Control keywords: {ctrl}\n"
        f"- DO NOT reformat unrelated lines; only touch the minimal span required."
    )

# ============== DYNAMIC PROPS (DECLARE ONLY, IN-PLACE) ============
_CLASS_LINE_RE = re.compile(r"(?m)^\s*(?:final\s+|abstract\s+)?class\s+[A-Za-z_][A-Za-z0-9_]*[^{]*\{")
_PROP_DECL_RE = re.compile(
    r"^\s*(?:(?P<vis>public|protected|private)|(?P<var>var))\s+(?:static\s+)?(?:\??[A-Za-z_\\][A-Za-z0-9_\\]*\s+)?\$(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b[^\n;]*;",
    re.M,
)
_THIS_PROP_RE = re.compile(r"\$this->([A-Za-z_][A-Za-z0-9_]*)\b")
_METHOD_RE = re.compile(r"^\s*(?:public|protected|private)?\s*function\b", re.M)
_DOCBLOCK_RE = re.compile(r"/\*\*[\s\S]*?\*/")

def _iter_class_regions(src: str):
    """Yield dicts with open_idx ( '{' ) and close_idx (matching '}' )."""
    for m in _CLASS_LINE_RE.finditer(src):
        open_idx = src.find("{", m.end() - 1)
        if open_idx == -1: continue
        i = open_idx + 1; depth = 1
        n = len(src)
        in_sq = in_dq = False
        in_line = in_block = False
        # rough heredoc/nowdoc skip
        in_here = False; here_tag = None
        while i < n and depth > 0:
            ch = src[i]; prev = src[i-1] if i > 0 else ""
            if in_here:
                # end of heredoc must be at start-of-line
                if ch == "\n":
                    j = i + 1
                    m2 = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*;?\s*$", src[j:src.find("\n", j) if src.find("\n", j) != -1 else n], re.M)
                    if m2 and m2.group(1) == here_tag:
                        in_here = False
            elif in_line:
                if ch == "\n": in_line = False
            elif in_block:
                if prev == "*" and ch == "/": in_block = False
            elif in_sq:
                if ch == "'" and prev != "\\": in_sq = False
            elif in_dq:
                if ch == '"' and prev != "\\": in_dq = False
            else:
                if ch == "'" : in_sq = True
                elif ch == '"': in_dq = True
                elif ch == "/" and i + 1 < n and src[i+1] == "/": in_line = True; i += 1
                elif ch == "/" and i + 1 < n and src[i+1] == "*": in_block = True; i += 1
                elif ch == "{": depth += 1
                elif ch == "}": depth -= 1
                elif ch == "<" and src[i:i+3] == "<<<":
                    # <<<TAG or <<<'TAG'
                    mhd = re.match(r"<<<\s*(?:'(?P<n1>[A-Za-z_][A-Za-z0-9_]*)'|\"(?P<n2>[A-Za-z_][A-Za-z0-9_]*)\"|(?P<n3>[A-Za-z_][A-Za-z0-9_]*))", src[i:])
                    if mhd:
                        in_here = True; here_tag = mhd.group("n1") or mhd.group("n2") or mhd.group("n3")
            i += 1
        if depth == 0:
            yield {"open_idx": open_idx, "close_idx": i - 1}

def _infer_prop_decl_style(src: str) -> str:
    var_count = len(re.findall(r"(?m)^\s*var\s+\$[A-Za-z_]", src))
    pub_count = len(re.findall(r"(?m)^\s*public\s+\$[A-Za-z_]", src))
    pro_count = len(re.findall(r"(?m)^\s*protected\s+\$[A-Za-z_]", src))
    pri_count = len(re.findall(r"(?m)^\s*private\s+\$[A-Za-z_]", src))
    if var_count >= (pub_count + pro_count + pri_count): return "var"
    if max(pub_count, pro_count, pri_count) == pub_count: return "public"
    if max(pub_count, pro_count, pri_count) == pro_count: return "protected"
    return "private"

def _find_insert_point(body: str) -> int:
    last_prop = None
    for pm in _PROP_DECL_RE.finditer(body):
        last_prop = pm
    if last_prop:
        e = body.find("\n", last_prop.end())
        return len(body) if e == -1 else e + 1
    first_m = _METHOD_RE.search(body)
    first_doc = _DOCBLOCK_RE.search(body, 0, first_m.start() if first_m else len(body))
    if first_doc:
        e = body.find("\n", first_doc.end())
        return len(body) if e == -1 else e + 1
    return 0

def _decl_text(names: List[str], style: Dict[str, Any], decl_style: str) -> str:
    indent = style.get("indent") or "    "
    eol = style.get("eol") or "\n"
    uniq = sorted(set(names))
    if decl_style == "var":
        return "".join(f"{indent}var ${n};{eol}" for n in uniq)
    return "".join(f"{indent}{decl_style} ${n};{eol}" for n in uniq)

def _fix_dynamic_properties_declare(src: str, style: Dict[str, Any]) -> Tuple[str, bool, str]:
    """Insert declarations IN-PLACE inside class body. Never touches header."""
    regions = list(_iter_class_regions(src))
    if not regions: return src, False, ""
    decl_style = _infer_prop_decl_style(src)
    new_src = src
    changed = False
    notes: List[str] = []
    # process from end to keep earlier indices valid
    for reg in reversed(regions):
        open_idx = reg["open_idx"]; close_idx = reg["close_idx"]
        body = new_src[open_idx + 1: close_idx]
        declared = {m.group("name") for m in _PROP_DECL_RE.finditer(body)}
        used = {m.group(1) for m in _THIS_PROP_RE.finditer(body)}
        missing = sorted([n for n in used if n not in declared])
        if not missing: continue
        insert_rel = _find_insert_point(body)
        insert_abs = open_idx + 1 + insert_rel
        text = _decl_text(missing, style, decl_style)
        new_src = new_src[:insert_abs] + text + new_src[insert_abs:]
        changed = True
        notes.append(f"declare[{decl_style}]: {', '.join(missing)}")
    return new_src, changed, (" ; ".join(notes) if notes else "")

# ============== RULE-BASED FIX ============
def apply_rule_based_fix(src: str, rules: List[Dict[str, Any]]):
    changed=False; note_parts=[]; code=src
    for r in rules:
        rid=r.get("id") or "rule"
        search=r.get("search"); replace=r.get("replace","")
        if not search: continue
        try:
            rx=re.compile(search, re.MULTILINE)
        except re.error as e:
            note_parts.append(f"{rid}: bad_regex({e})"); continue
        safe_replace=_sanitize_replacement(replace)
        try:
            new_code, n = rx.subn(safe_replace, code)
        except re.error as e:
            try:
                new_code, n = rx.subn(safe_replace.replace("\\", r"\\"), code)
            except Exception:
                note_parts.append(f"{rid}: bad_replace({e})"); continue
        if n>0:
            changed=True; code=new_code; note_parts.append(f"{rid} x{n}")
    return code, changed, (" ; ".join(note_parts) if note_parts else "")

# ============== CONTEXT SNIPPET ============
def _snippet_by_lines(src: str, lines: List[int], radius: int = 2) -> str:
    if not lines: return ""
    rows = src.splitlines()
    blocks=[]
    for ln in sorted({int(x) for x in lines if str(x).isdigit()}):
        lo = max(1, ln - radius); hi = min(len(rows), ln + radius)
        seg = "\n".join(f"{i:>5}: {rows[i-1]}" for i in range(lo, hi+1))
        blocks.append(f"--- around line {ln} ---\n{seg}")
    return "\n\n".join(blocks)

# ============== LLM (declare-only; no attributes) ============
def _llm_prompt(file_path: str, code: str, error_snippet: str, is_tpl: bool, style: Dict[str, Any]) -> str:
    return f"""
You are an experienced tester and PHP 8 migration assistant.
Fix runtime warnings/errors (Undefined array key/index/variable, deprecated APIs, dynamic property deprecations, and 'Passing null to parameter #1 ($string)') with the smallest possible change.

Project coding style:
{style_hint(style)}

Rules:
- ONLY modify PHP code in .php/.phtml/.tpl; keep HTML/Smarty intact unless necessary.
- Prefer ??, isset(), and PHP 8-safe APIs.
- Undefined vars: initialize with context-safe defaults ('' / 0 / [] / null).
- Missing offsets: use ($arr['k'] ?? default) / isset(...)?...:....
- htmlspecialchars()/mb_* expecting string: cast `(string)($x ?? '')`, preserve flags.
- Dynamic property deprecations: DO NOT add attributes. Declare missing class properties using the file's style (use `var $name;` if `var` is used, otherwise visibility).
- No @ suppression; no refactors; keep indentation/EOLs.

Return ONLY the FULL corrected file content.

=== FILE PATH ===
{file_path}

=== ERROR LINES (context) ===
{(error_snippet or '')[:2400]}

=== ORIGINAL FILE CONTENT ===
```php
{code}
```"""

def llm_fix(file_path: str, code: str, error_snippet: str):
    style = infer_style(code)
    system = "You are a precise code editor that outputs only code."
    prompt = _llm_prompt(file_path, code, error_snippet, file_path.lower().endswith((".tpl",".phtml")), style)
    try:
        out = chat(
            [{"role":"system","content":system},{"role":"user","content":prompt}],
            temperature=0.1, max_tokens=4096
        )
        m = re.search(r"```(?:php)?(.*)```", out, re.S | re.I)
        fixed = m.group(1).strip() if m else out.strip()
        if fixed and fixed != code:
            return fixed, True, "llm"
        return code, False, "llm:no_change"
    except Exception as e:
        return code, False, f"llm:error:{type(e).__name__}"

# ============== MAIN ============
def fix_selected(project_root: str, items: List[Dict[str, Any]], context_html: str = "", options: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """
    items: [{ "file": "/abs/or/rel/path.php|.tpl", "lines": [171, 272] }, ...]
    options: {"dynprops": "off|declare"}  (default declare)
    """
    results: List[Dict[str, Any]] = []
    if not items: return results
    options = options or {}
    dyn_mode = (options.get("dynprops") or "declare").lower()
    rules = load_rules()
    seen_files=set()

    for it in items:
        rel_or_abs = (it.get("file") or "").strip()
        if not rel_or_abs: continue

        candidate = remap_host_path(rel_or_abs)
        abs_path = candidate if os.path.isabs(candidate) else os.path.normpath(os.path.join(project_root, candidate))
        if abs_path in seen_files: continue
        seen_files.add(abs_path)

        if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
            results.append({"file": abs_path, "changed": False, "method": "skip", "note":"not_found"}); continue

        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                src = f.read()
        except Exception as e:
            results.append({"file": abs_path, "changed": False, "method": "skip", "note": f"read_error:{e}"}); continue

        backup = abs_path + ".bak"
        try:
            if not os.path.exists(backup): shutil.copy2(abs_path, backup)
        except Exception:
            pass

        style = infer_style(src)

        # 1) rules
        new_code, changed, note = apply_rule_based_fix(src, rules)
        method = "rules" if changed else "rules:none"

        # 2) dynamic props (declare, in-place)
        if dyn_mode == "declare" and abs_path.lower().endswith(".php"):
            new_code2, c2, n2 = _fix_dynamic_properties_declare(new_code, style)
            if c2:
                new_code = new_code2; changed = True
                method = f"{method}+dyn:declare" if "rules" in method else "dyn:declare"
                note = (note + (" ; " if note else "") + n2) if n2 else note

        # 3) LLM fallback
        if not changed:
            line_list = [int(x) for x in (it.get("lines") or []) if str(x).isdigit()]
            hint = _snippet_by_lines(new_code, line_list)
            error_context = (hint + ("\n\n" + (context_html or "") if context_html else ""))
            new_code3, c3, n3 = llm_fix(abs_path, new_code, error_context)
            if c3:
                new_code = new_code3; changed = True; method = "llm"; note = n3

        if changed and new_code != src:
            try:
                with open(abs_path, "w", encoding="utf-8") as f:
                    f.write(new_code)
            except Exception as e:
                results.append({"file": abs_path, "changed": False, "method": method, "note": f"write_error:{e}", "backup": backup}); continue

        results.append({"file": abs_path, "changed": bool(changed), "method": method, "note": note, "backup": backup})

    return results

def fix_errors(html_or_text: str, project_root: str) -> List[Dict[str, Any]]:
    targets = extract_php_targets(html_or_text)
    items = [{"file": p, "lines": [ln]} for (p, ln) in targets]
    return fix_selected(project_root, items, html_or_text, options={"dynprops": "declare"})
