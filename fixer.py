# fixer.py
import os, re, shutil
from typing import Dict, Any, List, Tuple
import yaml

from ai import chat

PATTERN_FILE = os.environ.get("PHP_FIX_PATTERNS") or "./patterns.yaml"

# ----------------------- main entry -------------------------------
def fix_errors(html_or_text: str, project_root: str) -> List[Dict[str, Any]]:
    """
    Returns list of patch records:
    {file, changed, method, note, backup}
    """
    targets = extract_php_targets(html_or_text)
    results: List[Dict[str, Any]] = []
    if not targets:
        return results

    for php_path, _line in targets:
        abs_path = php_path
        if not os.path.isabs(abs_path):
            abs_path = os.path.normpath(os.path.join(project_root, php_path))

        if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
            results.append({"file": abs_path, "changed": False, "method": "skip", "note":"not_found"})
            continue

        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                src = f.read()
        except Exception as e:
            results.append({"file": abs_path, "changed": False, "method": "skip", "note": f"read_error:{e}"})
            continue

        # backup once
        backup = abs_path + ".bak"
        try:
            if not os.path.exists(backup):
                shutil.copy2(abs_path, backup)
        except Exception:
            pass

        # 1) rules
        new_code, changed, note = apply_rule_based_fix(src)
        method = "rules" if changed else "rules:none"

        # 2) LLM fallback (minimal patch suggestion)
        if not changed:
            new_code2, changed2, note2 = llm_fix(abs_path, src, html_or_text)
            if changed2:
                new_code = new_code2
                changed = True
                method = "llm"
                note = note2

        if changed and new_code != src:
            try:
                with open(abs_path, "w", encoding="utf-8") as f:
                    f.write(new_code)
            except Exception as e:
                results.append({"file": abs_path, "changed": False, "method": method, "note": f"write_error:{e}", "backup": backup})
                continue

        results.append({"file": abs_path, "changed": bool(changed), "method": method, "note": note, "backup": backup})

    return results


def load_rules() -> List[Dict[str, Any]]:
    if not os.path.exists(PATTERN_FILE):
        return []
    with open(PATTERN_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    rules = data.get("rules") or []
    out: List[Dict[str, Any]] = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id") or "rule")
        search = r.get("search")
        replace = r.get("replace", "")
        note = r.get("note", "")
        if not isinstance(search, str):
            continue
        out.append({"id": rid, "search": search, "replace": replace, "note": note})
    return out

RULES: List[Dict[str, Any]] = load_rules()

_EXT = r"(?:php|phtml|tpl|inc)"
PHP_PATH_RE_HTML = re.compile(
    rf"in\s*<b>\s*([^<>\r\n]+?\.{_EXT})\s*</b>\s*on\s*line\s*<b>\s*(\d+)\s*</b>",
    re.IGNORECASE,
)
PHP_PATH_RE_TXT = re.compile(
    rf"(?:in|at)\s+((?:/|[A-Za-z]:\\)[^\s:<>\r\n]+?\.{_EXT})\s+on\s+line\s+(\d+)",
    re.IGNORECASE,
)

def extract_php_targets(html_or_text: str) -> List[Tuple[str, int]]:
    out: List[Tuple[str, int]] = []
    if not html_or_text:
        return out
    s = str(html_or_text)
    for m in PHP_PATH_RE_HTML.finditer(s):
        try: out.append((m.group(1).strip(), int(m.group(2))))
        except: pass
    for m in PHP_PATH_RE_TXT.finditer(s):
        try: out.append((m.group(1).strip(), int(m.group(2))))
        except: pass
    seen=set(); uniq=[]
    for p, ln in out:
        key=(os.path.normpath(p), ln)
        if key not in seen:
            seen.add(key); uniq.append((p, ln))
    return uniq

def apply_rule_based_fix(src: str):
    changed=False; note_parts=[]; code=src
    for r in RULES:
        rid=r.get("id") or "rule"
        search=r.get("search"); replace=r.get("replace","")
        if not search: continue
        try:
            rx=re.compile(search, re.MULTILINE)
        except re.error as e:
            note_parts.append(f"{rid}: bad_regex({e})"); continue
        new_code, n = rx.subn(replace, code)
        if n>0:
            changed=True; code=new_code; note_parts.append(f"{rid} x{n}")
    return code, changed, (" ; ".join(note_parts) if note_parts else "")

def llm_fix(file_path: str, code: str, error_snippet: str):
    system = "You are a precise code editor that outputs only code."
    prompt = f"""
You are an experienced tester and PHP 8 migration assistant.
Fix runtime error(s) shown below by editing this PHP file WITHOUT changing behavior.
- Prefer ??, isset checks, and PHP 8-safe APIs.
- Do not invent functions. Keep structure similar.
Return ONLY the FULL corrected file content.

=== FILE PATH ===
{file_path}

=== ERROR SNIPPET (context) ===
{(error_snippet or '')[:1800]}

=== ORIGINAL FILE CONTENT ===
```php
{code}
```"""
    try:
        out = chat(
            [{"role":"system","content":system},{"role":"user","content":prompt}],
            temperature=0.1, max_tokens=4096
        )
        # strip fences if any
        m = re.search(r"```php(.*)```", out, re.S|re.I)
        fixed = m.group(1).strip() if m else out.strip()
        if fixed and fixed != code:
            return fixed, True, "llm"
        return code, False, "llm:no_change"
    except Exception as e:
        return code, False, f"llm:error:{type(e).__name__}"
    
def fix_files_for_error_html(project_root: str, html: str) -> List[Dict[str, Any]]:
    print('iishee orloo..')
    results=[]
    targets = extract_php_targets(html)
    if not targets:
        return [{"file":"","changed":False,"method":"none","note":"no_targets"}]

    for php_path, line in targets:
        abs_path = php_path
        if not os.path.isabs(abs_path):
            abs_path = os.path.normpath(os.path.join(project_root, php_path))

        if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
            results.append({"file": abs_path, "changed": False, "method": "skip", "note":"not_found"})
            continue

        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()

        backup = abs_path + ".bak"
        try:
            if not os.path.exists(backup):
                shutil.copy2(abs_path, backup)
        except Exception:
            pass

        new_code, changed, note = apply_rule_based_fix(src)
        method = "rules" if changed else "rules:none"

        if not changed:
            new_code2, changed2, note2 = llm_fix(abs_path, src, html)
            if changed2:
                new_code = new_code2; changed = True; method = "llm"; note = note2

        if changed and new_code != src:
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(new_code)

        results.append({"file": abs_path, "changed": bool(changed), "method": method, "note": note, "backup": backup})
    return results
