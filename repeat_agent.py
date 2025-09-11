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
from webdriver_manager.chrome import ChromeDriverManager

warnings.filterwarnings('ignore')

def hashname(s: str, ext=".png"):
    h = hashlib.md5(s.encode('utf-8')).hexdigest()[:12]
    os.makedirs('./shots', exist_ok=True)
    return os.path.join('./shots', f'{h}{ext}')


def safe_status(url:str, timeout:10):
    try: return requests.get(url, timeout=timeout, verify=False).status_code
    except: return None

def lower(s: str) -> str:
    try: return s.lower()
    except: return s


PHP_ERROR_PATTERNS = [
    re.compile(r"(?:^|\b)(Fatal error|Parse error|Warning|Notice|Deprecated)\b", re.I),
    re.compile(r"in(/.+?\.php)\s+on line\s+(\d+)", re.I),
    re.compile(r"<br>(Fatal error|Warning|Notice|Deprecated)</b>:", re.I),
    re.compile(r"session save path cannot be changed when a session is active", re.I),
]

EXCLUDE_CSS_CLASSES = ("example", "docs", "documentation", "help", "guide", "cheatsheet")

def _visible(el):
    try: return el.is_displayed()
    except: return True

def extract_php_error(html: str, driver=None) -> Tuple[bool, str, str]:
    if not html: return False, "", ""
    if not PHP_ERROR_PATTERNS[0].search(html):
        return False, "", ""
    

