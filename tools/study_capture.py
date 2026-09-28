"""Explicit local consent-gated collection using the unchanged AUTHX wizard.

Only this launcher records uploads. It binds loopback, uses a temporary database,
disables SMTP, and requires a reviewed private registry and a browser consent action.
Never start a camera or microphone programmatically. Original uploads stay ignored.
"""
import argparse
import base64
import contextlib
from datetime import datetime, timezone
import html
import io
import json
from pathlib import Path
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import Config
from tools import comparison as harness
from tools import comparison_import as importer
from tools import volunteer_study as study_tools


@contextlib.contextmanager
def capture_app(study_path, trial_id, output, *, protocol_freeze):
    from flask import abort, g, jsonify, render_template, request
    import jwt
    info = study_tools.load_study(study_path, dataset_required=False)
    pinned = study_tools.read_json(protocol_freeze)
    study_tools.require(pinned.get('phase') == 'before_collection', 'A precollection protocol pin is required')
    study_tools.assert_frozen(info, pinned)
    study_tools.require(trial_id in info['trials'], 'Unknown predeclared trial')
    study_tools.require(info['study']['protocol'].get('declaredBeforeCollection') is True, 'Declare protocol before collecting')
    trial = info['trials'][trial_id]
    # Attack source identities must be assigned before collection, not after scores.
    sources = trial.get('sourceSubjectIds')
    study_tools.require(isinstance(sources, list) and sources, 'Declare all source identities on the planned trial before collection')
    for sid in {trial['subjectId'], *sources}:
        study_tools.require(sid in info['subjects'] and info['subjects'][sid]['split'] == trial['split'], 'Source consent/split missing')
        if trial['category'] in ('photo', 'screen_replay') and sid in sources:
            study_tools.require(info['subjects'][sid].get('replayPermitted') is True, 'Source replay permission missing')
    output = Path(output).resolve()
    study_tools.require(output.is_relative_to((ROOT / '.runtime').resolve()), 'Capture output must stay under ignored .runtime')
    output.mkdir(parents=True, exist_ok=False)
    (output / 'protocol-freeze.json').write_bytes(Path(protocol_freeze).read_bytes())
    original = harness.original_inventory()
    old = {key: getattr(Config, key) for key in ('DATABASE_PATH', 'VERIFICATION_PROFILE', 'SMTP_USER', 'SMTP_PASSWORD', 'JWT_SECRET')}
    with tempfile.TemporaryDirectory(prefix='authx-study-db-') as temp:
        try:
            Config.DATABASE_PATH = Path(temp) / 'capture.db'
            Config.VERIFICATION_PROFILE = 'v2'
            Config.SMTP_USER = Config.SMTP_PASSWORD = ''
            Config.JWT_SECRET = secrets.token_urlsafe(48)
            from app import create_app, models
            with contextlib.redirect_stdout(io.StringIO()):
                app = create_app()
            app.config.update(TESTING=False)
            student = models.get_user_by_username('avinash')
            token = jwt.encode({'sub': str(student['id'])}, app.config['JWT_SECRET'], algorithm='HS256')
            page_key, consent_key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            state = {'consented': False, 'ended': False, 'events': [], 'sessions': {}, 'enrollment': None, 'cameraConfirmed': False}
            lock = threading.RLock()
            ledger = {'schemaVersion': 'authx-private-capture-1', 'studyId': info['study']['studyId'], 'trialId': trial_id,
                'studySha256BeforeCapture': harness.digest(info['path'].read_bytes()), 'sourceBeforeCapture': study_tools.source_inventory(),
                'configBeforeCapture': study_tools.config_inventory(), 'trial': trial, 'profile': 'v2',
                'protectedBeforeCapture': original['fileHashes'],
                'protocolFreezeSha256': harness.digest(Path(protocol_freeze).read_bytes()),
                'captureTiming': 'Existing AuthXCapture performance/sample clocks and original server challenge/flash.',
                'consentAcknowledgedAt': None, 'terminalOutcomeRecorded': False, 'events': [], 'sessions': [],
                'enrollment': None}

            def authorized():
                return request.args.get('key') == page_key or request.headers.get('X-AuthX-Study') == consent_key

            @app.before_request
            def protect_collection():
                if request.remote_addr not in ('127.0.0.1', '::1', None):
                    abort(403)
                if request.path.startswith('/static/'):
                    return None
                if not authorized():
                    abort(403)
                if request.method == 'POST' and request.path.startswith('/api/'):
                    if not state['consented'] or state['ended']:
                        return jsonify(ok=False, reason='study_consent_required'), 403
                    if not state['cameraConfirmed']:
                        return jsonify(ok=False, reason='study_camera_not_confirmed'), 403
                    # Disable faculty/admin/auth/standalone routes in this collector.
                    allowed = request.path == '/api/face/enroll' or request.path == '/api/session/start'
                    allowed |= request.path.startswith('/api/session/') and request.path.rsplit('/', 1)[-1] in ('look', 'speak', 'trust', 'certificate')
                    if not allowed:
                        abort(403)
                    if request.path == '/api/session/start' and len(state['sessions']) >= 2:
                        return jsonify(ok=False, reason='study_two_session_limit'), 409
                    if request.path == '/api/face/enroll' and state['sessions']:
                        return jsonify(ok=False, reason='study_enrollment_frozen'), 409
                    if request.path.startswith('/api/session/') and request.path != '/api/session/start':
                        sid = request.path.split('/')[3]
                        if sid not in state['sessions']:
                            abort(403)
                    g.study_began = time.perf_counter()
                    # Retain exact request body bytes; no authorization headers.
                    g.study_body = request.get_data(cache=True)
                return None

            @app.after_request
            def save_original(response):
                if not hasattr(g, 'study_began'):
                    return response
                seconds = time.perf_counter() - g.study_began
                with lock:
                    index = len(state['events'])
                    payload_name = f'upload-{index:04}.json'
                    (output / payload_name).write_bytes(g.study_body)
                    stage = request.path.rsplit('/', 1)[-1]
                    body = response.get_json(silent=True) or {}
                    sid = body.get('sessionId') if stage == 'start' else (request.view_args or {}).get('session_id')
                    if stage == 'start' and body.get('ok') is True:
                        session = models.get_session(sid)
                        state['sessions'][sid] = {'id': sid, 'sessionAttempt': len(state['sessions']) + 1,
                            'word': session['challenge_word'], 'flashStartMs': session['flash_start_ms'],
                            'startedAt': session['started_at'], 'verificationProfile': session['verification_profile']}
                    event = {'stage': stage, 'sessionId': sid, 'upload': payload_name,
                        'uploadSha256': harness.digest(g.study_body), 'receivedAt': datetime.now(timezone.utc).isoformat(),
                        'seconds': seconds, 'httpStatus': response.status_code,
                        'ok': body.get('ok') is True, 'reason': body.get('reason') or body.get('error'),
                        'attemptsUsed': body.get('attemptsUsed')}
                    state['events'].append(event)
                    if stage == 'enroll':
                        if body.get('enrolled') is True:
                            embedding = models.get_user_by_username('avinash')['face_embedding']
                            name = f'enrollment-{index:04}.json'
                            (output / name).write_text(embedding, encoding='utf-8')
                            state['enrollment'] = {'upload': payload_name, 'embedding': name, 'ok': True,
                                'embeddingSha256': harness.digest(embedding.encode('utf-8')),
                                'method': 'v2_five_image', 'seconds': seconds, 'subjectId': trial['subjectId']}
                        else:
                            event['enrollmentFailed'] = True
                return response

            @app.get('/study')
            def page():
                if state['ended']:
                    return 'Collection ended. Close this tab.', 410
                # Reuse the existing view and capture modules without modifying
                # product routes/templates or storing a token in localStorage.
                rendered = render_template('home.html', role='student', heading='Private volunteer collection', creators=(),
                    frame_long_side=app.config['FRAME_LONG_SIDE'], jpeg_quality=app.config['JPEG_QUALITY'],
                    flash_ms=app.config['FLASH_DURATION_MS'], sample_rate=app.config['SAMPLE_RATE'], enrollment_samples=5)
                bootstrap = '''<script>
const nativeFetch = window.fetch.bind(window);
window.fetch = async (url, options = {}) => {
  const headers={...options.headers, Authorization: 'Bearer ' + TOKEN, 'X-AuthX-Study': KEY};
  if(String(url).startsWith('/api/')) {
    const tracks=[...studyStreams].flatMap(stream=>stream.getVideoTracks()).filter(track=>track.readyState==='live');
    if(tracks.length) {
      const key=await cameraKey(tracks[tracks.length-1].getSettings().deviceId);
      const verified=await nativeFetch('/study/device', {method:'POST', headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({deviceKeySha256:key})});
      if(!verified.ok) { document.getElementById('study-note').textContent='The selected camera differs from this trial. Select the declared camera.'; return verified; }
    }
  }
  return nativeFetch(url, {...options, headers});
};
let resolveStudyRole;
window.AuthXShell = {requireRole: () => new Promise(resolve => { resolveStudyRole=resolve; })};
const studyStreams = new Set();
const nativeGetUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
async function cameraKey(deviceId) {
  const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(deviceId || ''));
  return [...new Uint8Array(bytes)].map(b=>b.toString(16).padStart(2,'0')).join('');
}
navigator.mediaDevices.getUserMedia = async constraints => {
  const stream=await nativeGetUserMedia(constraints); studyStreams.add(stream);
  if(stream.getVideoTracks().length) document.getElementById('study-note').textContent='Active camera key: '+await cameraKey(stream.getVideoTracks()[0].getSettings().deviceId);
  return stream;
};
</script>'''.replace('TOKEN', json.dumps(token)).replace('KEY', json.dumps(consent_key))
                # Remove shell.js: its storage/role bootstrap is replaced only here.
                rendered = rendered.replace('<script src="/static/js/shell.js"></script>', '')
                rendered = re.sub(r'<link[^>]+href="https://fonts\.[^"]+"[^>]*>', '', rendered)
                rendered = rendered.replace('<script src="/static/js/evidence.js">', bootstrap + '<script src="/static/js/evidence.js">')
                banner = ('<div class="panel" id="study-consent"><p>Trial ' + html.escape(trial_id) + ': ' + html.escape(trial['category']) +
                    ' / ' + html.escape(trial['lighting']) + ' / camera ' + html.escape(trial['cameraId']) +
                    '.</p><p>Original face/video/audio uploads will be saved privately. The operator must verify signed consent, '
                    'the selected camera, declared source identities and lighting. Enroll the named enrollment subject before switching to an attack source. '
                    'For wrong-word trials, say a different word on every submission. Keep bystanders outside view.</p>'
                    '<button id="study-agree">I agree to recording for this trial</button> '
                    '<button id="study-end">End collection and stop devices</button><p id="study-note"></p></div>')
                final = '''<script>
document.getElementById('wizard').hidden = true;
document.getElementById('study-agree').onclick = async () => {
  const r = await fetch('/study/consent', {method:'POST'});
  if(r.ok) { resolveStudyRole({role:'student', enrolled:false});
    document.getElementById('study-agree').disabled=true; }
};
document.getElementById('study-end').onclick = async () => {
  if(document.getElementById('live').srcObject && document.getElementById('camera').disabled) {
    document.getElementById('study-note').textContent='Wait until recording and scoring finish, then end collection.'; return;
  }
  const video=document.getElementById('live');
  studyStreams.forEach(stream=>stream.getTracks().forEach(t=>t.stop()));
  document.getElementById('wizard').hidden=true;
  const r=await fetch('/study/end', {method:'POST'});
  document.getElementById('study-note').textContent=r.ok?'Original uploads saved. Close this tab.':'Wait until recording finishes, then end again.';
};
</script>'''
                return rendered.replace('<section id="wizard"', banner + '<section id="wizard"').replace('</body>', final + '</body>')

            @app.post('/study/consent')
            def consent():
                if state['ended']:
                    abort(409)
                state['consented'] = True
                if not ledger['consentAcknowledgedAt']:
                    ledger['consentAcknowledgedAt'] = datetime.now(timezone.utc).isoformat()
                return jsonify(ok=True)

            @app.post('/study/device')
            def device():
                if not state['consented'] or state['ended']:
                    abort(403)
                value = request.get_json(silent=True) or {}
                state['cameraConfirmed'] = value.get('deviceKeySha256') == info['cameras'][trial['cameraId']]['deviceKeySha256']
                if not state['cameraConfirmed']:
                    return jsonify(ok=False, reason='study_camera_not_confirmed'), 403
                ledger['cameraDeviceKeySha256'] = value['deviceKeySha256']
                return jsonify(ok=True)

            @app.post('/study/end')
            def end():
                with lock:
                    if not state['consented']:
                        abort(403)
                    if any(models.get_session(s)['speak_token'] for s in state['sessions']):
                        return jsonify(ok=False, reason='speak_in_progress'), 409
                    if state['ended']:
                        return jsonify(ok=True)
                    state['ended'] = True
                    ledger.update(terminalOutcomeRecorded=True, endedAt=datetime.now(timezone.utc).isoformat(),
                        events=state['events'], sessions=list(state['sessions'].values()), enrollment=state['enrollment'])
                    for item in ledger['sessions']:
                        session = models.get_session(item['id'])
                        item.update(machineRiskLabel=session['machine_risk_label'],
                                    completed=models.get_certificate_for_session(item['id']) is not None,
                                    speakSubmissionsSpent=session['speak_attempts'])
                    study_tools.write_json(output / 'capture-ledger.json', ledger)
                    return jsonify(ok=True)
            yield app, '/study?key=' + page_key
        finally:
            for key, value in old.items():
                setattr(Config, key, value)
            study_tools.require(harness.original_inventory() == original, 'Protected originals changed during collection')


def export_capture(capture, output):
    capture, output = Path(capture).resolve(), Path(output).resolve()
    study_tools.require(output.is_relative_to((ROOT / '.runtime').resolve()), 'Private dataset output must stay under .runtime')
    ledger_path = capture / 'capture-ledger.json'
    ledger = study_tools.read_json(ledger_path)
    study_tools.require(ledger.get('schemaVersion') == 'authx-private-capture-1' and ledger.get('terminalOutcomeRecorded') is True
                        and ledger.get('consentAcknowledgedAt'), 'Missing consent-gated terminal capture ledger')
    enrollment = ledger.get('enrollment')
    study_tools.require(enrollment and enrollment.get('ok') is True and enrollment.get('method') == 'v2_five_image', 'No successful actual v2 enrollment capture')
    output.mkdir(parents=True, exist_ok=False)
    trial = ledger['trial']
    # Copy private originals/provenance; no media goes into the ordinary DB/report.
    (output / 'capture-ledger.json').write_bytes(ledger_path.read_bytes())
    (output / 'protocol-freeze.json').write_bytes(study_tools.private_path(capture, 'protocol-freeze.json').read_bytes())
    for event in ledger['events']:
        raw = study_tools.private_path(capture, event['upload']).read_bytes()
        study_tools.require(harness.digest(raw) == event['uploadSha256'], 'Original upload bytes changed')
        (output / event['upload']).write_bytes(raw)
    embedding = study_tools.private_path(capture, enrollment['embedding']).read_bytes()
    study_tools.require(harness.digest(embedding) == enrollment['embeddingSha256'], 'Original enrollment vector changed')
    (output / 'enrollment.json').write_bytes(embedding)
    # Preserve the source-named embedding as referenced by the immutable ledger.
    (output / enrollment['embedding']).write_bytes(embedding)
    cases, metadata = [], []
    for session in ledger['sessions']:
        events = []
        for event in ledger['events']:
            if event['sessionId'] != session['id'] or event['stage'] not in ('look', 'speak'):
                continue
            raw = study_tools.private_path(capture, event['upload']).read_bytes()
            study_tools.require(harness.digest(raw) == event['uploadSha256'], 'Original upload bytes changed')
            events.append({'stage': event['stage'], 'payload': json.loads(raw)})
        if not events:
            raise ValueError('Started session has no original submission; record operational issue separately')
        case_id = harness.identifier(ledger['trialId'] + '-a' + str(session['sessionAttempt']))
        sequence, records = importer.export_submissions(events, output / case_id)
        for event in sequence:
            for frame in event['frames']:
                frame['path'] = case_id + '/' + frame['path']
            if event.get('wav'):
                event['wav'] = case_id + '/' + event['wav']
        for index, record in enumerate(records):
            record['id'] = harness.identifier(case_id + '-r' + str(index + 1))
        category = trial['category']
        cases.append({'id': case_id, 'fixtureCategory': 'consented', 'consentRecorded': True, 'split': trial['split'],
            'timingProvenance': 'captured_sample_clock', 'expectedWord': session['word'], 'flashStartMs': session['flashStartMs'],
            'enrollment': 'common', 'groundTruth': {'category': category, 'safeExpected': category == 'genuine', 'wordMatch': study_tools.declared_word_truth(trial)},
            'submissions': sequence})
        metadata.append({'caseId': case_id, 'trialId': ledger['trialId'], 'sessionAttempt': session['sessionAttempt'],
            'enrollmentSubjectId': trial['subjectId'], 'sourceSubjectIds': trial['sourceSubjectIds'],
            'authenticity': 'original_browser_uploads', 'terminalOutcomeRecorded': True,
            'captureLedger': 'capture-ledger.json', 'captureLedgerSha256': harness.digest(ledger_path.read_bytes()),
            'recordings': records})
    manifest = {'schemaVersion': harness.DATASET_VERSION, 'datasetId': ledger['trialId'],
        'enrollments': {'common': {'method': 'existing_embedding', 'path': 'enrollment.json'}}, 'cases': cases}
    study_tools.write_json(output / 'manifest.json', manifest)
    prepared = harness.load_dataset(output / 'manifest.json')
    for row, case in zip(metadata, prepared['cases']):
        row['originalInputSha256'] = case.input_hash
    study_tools.write_json(output / 'case-metadata.json', metadata)
    return output / 'manifest.json'


def assemble(study_path, exports, output, ready_study):
    """Combine private lossless exports without changing consent or recorded truth."""
    study_path, output, ready_study = Path(study_path).resolve(), Path(output).resolve(), Path(ready_study).resolve()
    info = study_tools.load_study(study_path, dataset_required=False)
    study_tools.require(output.is_relative_to(study_path.parent) and ready_study.parent == study_path.parent
                        and output.is_relative_to((ROOT / '.runtime').resolve()), 'Assembled dataset and ready registry must remain in private study directory')
    study_tools.require(not output.exists() and not ready_study.exists(), 'Choose fresh assembled output and ready registry')
    output.mkdir(parents=True)
    manifest = {'schemaVersion': harness.DATASET_VERSION, 'datasetId': info['study']['studyId'], 'enrollments': {}, 'cases': []}
    cases, seen = [], set()
    for export in exports:
        export = Path(export).resolve()
        raw = study_tools.read_json(export / 'manifest.json')
        label = harness.identifier(raw['datasetId'])
        study_tools.require(label not in seen and label in info['trials'], 'Duplicate or undeclared exported trial')
        seen.add(label)
        shutil.copytree(export, output / label)
        for key, enrollment in raw['enrollments'].items():
            name = harness.identifier(label + '-' + key)
            manifest['enrollments'][name] = {**enrollment, 'path': label + '/' + enrollment['path']}
        for case in raw['cases']:
            case['enrollment'] = label + '-' + case['enrollment']
            for event in case['submissions']:
                for frame in event['frames']:
                    frame['path'] = label + '/' + frame['path']
                if event.get('wav'):
                    event['wav'] = label + '/' + event['wav']
            manifest['cases'].append(case)
        for row in study_tools.read_json(export / 'case-metadata.json'):
            row['captureLedger'] = (output.relative_to(study_path.parent) / label / row['captureLedger']).as_posix()
            cases.append(row)
    study_tools.write_json(output / 'manifest.json', manifest)
    prepared = {c.case_id: c for c in harness.load_dataset(output / 'manifest.json')['cases']}
    study_tools.require(all(prepared[r['caseId']].input_hash == r['originalInputSha256'] for r in cases), 'Assembly changed original media or enrollment')
    ready = {**info['study'], 'datasetManifest': (output.relative_to(study_path.parent) / 'manifest.json').as_posix(), 'cases': cases}
    study_tools.write_json(ready_study, ready)
    study_tools.load_study(ready_study)
    return ready_study


def camera_inventory_app():
    """Device inventory only; no Flask factory, app DB, saved images or audio."""
    from flask import Flask, abort, request
    app = Flask('authx-camera-inventory')

    @app.get('/')
    def page():
        if request.remote_addr not in ('127.0.0.1', '::1', None):
            abort(403)
        return '''<!doctype html><html><head><meta charset="utf-8"><title>Local camera inventory</title></head>
<body><h1>Local camera inventory</h1><p>Use the same browser and port for collection. No image or audio is saved.
Keep bystanders outside the view before opening a device.</p><button id="allow">Allow camera labels</button><pre id="result"></pre>
<script>document.getElementById('allow').onclick=async()=>{
let stream;try{
stream=await navigator.mediaDevices.getUserMedia({video:true,audio:false});
const devices=(await navigator.mediaDevices.enumerateDevices()).filter(d=>d.kind==='videoinput');
const cameras=[];for(const [i,d] of devices.entries()){
const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(d.deviceId));
cameras.push({id:'cam'+(i+1),description:d.label,deviceKeySha256:[...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,'0')).join('')});}
document.getElementById('result').textContent=JSON.stringify(cameras,null,2);
}catch(error){document.getElementById('result').textContent='Camera access failed: '+error.name;}
finally{if(stream)stream.getTracks().forEach(t=>t.stop());}
};</script></body></html>'''
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    collect = sub.add_parser('collect'); collect.add_argument('study', type=Path); collect.add_argument('--trial', required=True)
    collect.add_argument('--protocol-freeze', type=Path, required=True)
    collect.add_argument('--output', type=Path, required=True); collect.add_argument('--port', type=int, default=5017)
    export = sub.add_parser('export'); export.add_argument('capture', type=Path); export.add_argument('--output', type=Path, required=True)
    merge = sub.add_parser('assemble'); merge.add_argument('study', type=Path); merge.add_argument('--exports', type=Path, nargs='+', required=True)
    merge.add_argument('--output', type=Path, required=True); merge.add_argument('--ready-study', type=Path, required=True)
    devices = sub.add_parser('cameras'); devices.add_argument('--port', type=int, default=5017)
    args = parser.parse_args()
    if args.command == 'cameras':
        print(f'Open http://127.0.0.1:{args.port}/ and click Allow camera labels; no recordings are stored. Ctrl+C when finished.')
        camera_inventory_app().run(host='127.0.0.1', port=args.port, debug=False, use_reloader=False, threaded=False)
    elif args.command == 'export':
        export_capture(args.capture, args.output); print('Exported original local media/timing and anonymous case metadata.')
    elif args.command == 'assemble':
        assemble(args.study, args.exports, args.output, args.ready_study); print('Assembled private original recordings; consent and subject splits preserved.')
    else:
        with capture_app(args.study, args.trial, args.output, protocol_freeze=args.protocol_freeze) as (app, page):
            print(f'Open http://127.0.0.1:{args.port}{page} on this laptop. Review consent before Allow camera. Ctrl+C after End collection.')
            app.run(host='127.0.0.1', port=args.port, debug=False, use_reloader=False, threaded=False)


if __name__ == '__main__':
    try:
        main()
    except ValueError as exc:
        print(str(exc), file=sys.stderr); sys.exit(2)
