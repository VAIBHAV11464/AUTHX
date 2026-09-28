"""Explicit subprocess inventory, retained logs, actual counts and skips."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PYTHON = ('smoke_api', 'verification_profiles', 'uploads_quality', 'enrollment_matching', 'speak_identity',
          'landmark_runtime', 'capture_timing', 'landmark_evidence', 'offline_speech', 'challenge_word',
          'decision_gates', 'evidence_summaries', 'session_lifecycle', 'certificate_atomic')
NODE = ('wizard_enrollment', 'capture_timing', 'wizard_speech', 'evidence_summaries', 'session_lifecycle')

def run(stage, extra=()):
    env = dict(os.environ, SMTP_USER='', SMTP_PASSWORD='', VERIFICATION_PROFILE='legacy',
               AUTHX_TEST_OUTPUT_DIR=str(OUT / stage))
    (OUT / stage).mkdir(exist_ok=True)
    commands = [('smoke' if name == 'smoke_api' else 'unittest', [sys.executable, f'tests/{name}.py'])
                for name in (*PYTHON, *extra)]
    commands += [('node_simulation', ['node', f'tests/{name}.js']) for name in NODE]
    commands += [('compile', [sys.executable, '-m', 'compileall', '-q', 'app', 'tests', 'tools', 'config.py'])]
    commands += [('js_syntax', ['node', '--check', str(p.relative_to(ROOT))])
                 for p in sorted((ROOT / 'app/static/js').glob('*.js'))]
    commands += [('dependencies', [sys.executable, '-m', 'pip', 'check'])]
    results = []
    for index, (kind, command) in enumerate(commands):
        started = time.perf_counter()
        path = OUT / stage / f'{index:02}-{Path(command[-1]).stem}.log'
        with path.open('x', encoding='utf-8') as log:
            process = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        content = path.read_text(encoding='utf-8', errors='replace')
        count = re.search(r'Ran (\d+) tests?', content)
        skips = re.search(r'skipped=(\d+)', content)
        executed = int(count[1]) if count else len(re.findall(r'^ok ', content, re.M)) if kind == 'smoke' else None
        row = {'kind': kind, 'command': command, 'exitCode': process.returncode,
               'log': str(path.relative_to(OUT)), 'seconds': round(time.perf_counter() - started, 3),
               'executed': executed, 'skips': int(skips[1]) if skips else 0}
        if kind == 'unittest' and (not executed or 'OK' not in content):
            row['verificationError'] = 'Missing nonzero unittest completion'
        if kind == 'smoke' and 'smoke ok' not in content:
            row['verificationError'] = 'Missing smoke completion'
        results.append(row)
        print(f'{index + 1}/{len(commands)} exit {process.returncode}, count {executed}: {command[-1]}', flush=True)
        report = {'stage': stage, 'commands': results,
                  'pythonTests': sum(r['executed'] or 0 for r in results if r['kind'] == 'unittest'),
                  'smokeChecks': sum(r['executed'] or 0 for r in results if r['kind'] == 'smoke'),
                  'skips': sum(r['skips'] for r in results),
                  'passed': all(r['exitCode'] == 0 and not r.get('verificationError') for r in results)}
        (OUT / f'{stage}-result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report['passed']

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage')
    parser.add_argument('--extra', nargs='*', default=[])
    args = parser.parse_args()
    sys.exit(not run(args.stage, args.extra))
