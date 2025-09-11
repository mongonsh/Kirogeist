import os, io, uuid, threading, time
from urllib.parse import urlparse
from flask import Flask, request, jsonify, send_file, render_template
import pandas as pd

from agents import (
    EndpointCollector, Checker, Fixer, AdvisorAI, write_with_images_fit
)

app = Flask(__name__, template_folder='templates', static_folder=None)
JOBS = {}
REPORTS = {}

def run_job(job_id, base_url, project_root, endpoints_text, excel_path, login_url, login_id, login_pw):
    job = JOBS[job_id]
    try:
        urls = []
        if excel_path and os.path.exists(excel_path):
            df = pd.read_excel(excel_path)
            urls.extend([u for u in df['url'].dropna().astype(str).tolist()])
        if endpoints_text:
            urls.extend([l.strip() for l in endpoints_text.splitlines() if l.strip()])
        urls = [urljoin(base_url, u) if u.startswith('/') else u for u in urls]
        urls = list(dict.fromkeys(urls))
        collector = EndpointCollector(base_url, seeds= urls)
        checker = Checker()
        fixer = Fixer(project_root=project_root, pattern_file='patterns.yaml')
        advisor = AdvisorAI(fixer)
        checker.login_if_needed(login_url, login_id, login_pw)

        eps = collector.collect()
        total = len(eps)
        job.update({'total': total, 'progress': 0, 'summary':{'passed':0, 'failed':0}, 'errors':{}, 'status':'running'})
        results = []
        for i, ep in enumerate(eps, 1):
            pr = checker.check_one(ep)
            note = pr['error_snippet']
            src = 'none'
            if pr['is_error']:
                page_html = (checker.driver.page_source or '').lower()
                file_hint = pr.get('file_path') or ''
                fixed, src, fnote = advisor.propose_and_fix(page_html, pr['error_snippet'], file_hint)
                note = fnote or note
                if fixed:
                    time.sleep(0.5)
                    pr2 = checker.check_one(ep)
                    pr.update(pr2)
            
            status_text = 'テスト成功' if not pr['is_error'] else 'テスト失敗'
            results.append({
                'url': pr['url'],
                'タイトル': pr['title'],
                'ステータス': status_text,
                'screenshot':pr['screenshot'],
                '備考': f"[{src}] {note}" if src!="none" else note,
                "HTTP":pr['http_status'],
                'tester': 'Mongoo',
                "tested_at": pd.Timestamp.utcnow().tz_localize('UTC').tz_convert('Asia/Tokyo').strftime('%Y-%m-%d %H:%M:%S')
            })

            if pr['is_error']:
                job['summary']['failed'] += 1
                key = (pr['error_snippet'][:120] or 'error').strip()
                job['errors']['key'] = job['errors'].get(key, 0) + 1
            else:
                job['summary']['passed'] += 1
            job['progress'] = i
        checker.close()


        df = pd.DataFrame(results)
        out_buf = io.BytesIO()
        tmp_path = f'/tmp/report_{job_id}.xlsx'
        write_with_images_fit(df, tmp_path, image_col='screenshot', display_col_name='スクリーンショット')
        with open(tmp_path, 'rb') as f: out_buf.write(f.read())
        REPORTS[job_id] = out_buf.getvalue()

        job['status'] = 'done'
        job['download_url'] = f'/download/{job_id}'
    
    except Exception as e:
        job['status'] = 'error'
        job['error_msg'] = str(e)
    
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/run-test', methods=['POST'])
def run_test():
    base_url = request.form.get('base_url', '').strip()
    project_root = request.form.get('project_root', '').strip()
    test_type = request.form.get('test_type', 'smoke').strip()
    login_url = request.form.get('login_url', '').strip()
    login_id = request.form.get('login_id', '').strip()
    login_pw = request.form.get('login_pw', '').strip()
    endpoints_text = request.form.get('endpoints_text', '').strip()

    excel_path = None
    f = request.files.get('excel_file')
    if f and f.filename:
        excel_path = os.path.join('/tmp', f'endpoints_{uuid.uuid4().hex}.xlsx')
        f.save(excel_path)
    
    job_id = uuid.uuid4().hex[:8]
    JOBS[job_id] = {
        "ok": True,
        "status": "queued",
        "progress": 0,
        "total": 0,
        "summary": {"passed": 0, "failed": 0},
        "errors": {},
    }

    t = threading.Thread(target=run_job, args=(
        job_id, base_url, project_root, endpoints_text, excel_path, login_url, login_id, login_pw), daemon=True)
    t.start()

    return jsonify({
        "ok": False,
        "job_id": job_id
    })


@app.route('/job/<job_id>/status')
def job_status(job_id):
    job = JOBS.get(job_id)
    if not job: return jsonify(
        {
            "ok": False,
            "error": "job not found"
        }, 404
    )
    return jsonify(
        {"ok": True, "job": job}
    )


@app.route('/download/<job_id>')
def download_report(job_id):
    buf = REPORTS.get(job_id)
    if not buf: return "Not ready", 404
    return send_file(
        io.BytesIO(buf),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f'php8_migration_report_{job_id}.xlsx'
    )

if __name__ == '__main__':
    app.run('0.0.0.0', port=5000, debug=True)