"""Prepare labeled static portrait/SAPI smoke captures once; never edit originals."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import wave

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.comparison import DATASET_VERSION


def prepare(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    fixtures = ROOT / '.runtime/fixtures'
    portrait = cv2.imread(str(fixtures / 'portrait.jpg'))
    if portrait is None:
        raise ValueError('The documented local public portrait is required')
    scale = min(1., 640 / max(portrait.shape[:2]))
    resized = cv2.resize(portrait, (round(portrait.shape[1] * scale), round(portrait.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    if not cv2.imwrite(str(output / 'portrait.jpg'), resized, [cv2.IMWRITE_JPEG_QUALITY, 70]):
        raise ValueError('Cannot write portrait fixture')
    sources = {'portrait.jpg': hashlib.sha256((fixtures / 'portrait.jpg').read_bytes()).hexdigest()}
    for name in ('amber', 'bridge', 'phrase'):
        source = fixtures / f'speech-{name}.wav'
        sources[source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
        with wave.open(str(source), 'rb') as wav:
            rate = wav.getframerate()
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise ValueError('Expected the documented mono PCM16 SAPI fixture')
            raw = wav.readframes(wav.getnframes())
        if len(raw) > rate * 3 * 2:
            raise ValueError('Demo will not truncate speech')
        with wave.open(str(output / f'{name}.wav'), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(raw + b'\0' * (rate * 3 * 2 - len(raw)))
    frames = [{'path': 'portrait.jpg', 'tMs': i * 50} for i in range(60)]
    cases = []
    for name in ('amber', 'bridge', 'phrase', 'invalid-timing'):
        look = [dict(frame) for frame in frames]
        if name == 'invalid-timing':
            look[10]['tMs'] = look[9]['tMs']  # Actual rejection, no harness repair.
        cases.append({'id': 'static-' + name, 'fixtureCategory': 'synthetic', 'split': 'demo',
                      'timingProvenance': 'synthetic_schedule', 'source': 'Public portrait repeated on a synthetic clock; local Microsoft David Desktop SAPI audio',
                      'expectedWord': 'amber', 'flashStartMs': 2000, 'enrollment': 'public-portrait',
                      'groundTruth': {'category': 'unknown', 'safeExpected': None, 'wordMatch': name in ('amber', 'invalid-timing')},
                      'attempts': [{'lookFrames': look, 'speakFrames': frames,
                                    'wav': ('amber' if name == 'invalid-timing' else name) + '.wav', 'audioStartMs': 0}]})
    manifest = {'schemaVersion': DATASET_VERSION, 'datasetId': 'public-sapi-static-smoke',
                'provenance': {'originalFixtureHashes': sources,
                               'portrait': 'Existing documented Google public portrait; scaled once to long side <=640 and JPEG quality 70 (browser capture encoding).',
                               'audio': 'Existing documented Microsoft David Desktop SAPI synthetic words; silence padded once to exactly three seconds.',
                               'timing': 'Synthetic 50 ms schedule; these are not measured camera/audio hardware timestamps.',
                               'truth': 'Only word agreement is known; no consented genuine/negative biometric evaluation labels.'},
                'enrollments': {'public-portrait': {'method': 'legacy_single_image', 'path': 'portrait.jpg'}}, 'cases': cases}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Prepared four labeled smoke cases; original fixture bytes untouched.')
    return output / 'manifest.json'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.runtime/comparison-fixtures')
    prepare(parser.parse_args().output)
