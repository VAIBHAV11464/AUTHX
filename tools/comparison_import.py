"""Import existing upload JSON without changing media bytes or capture times.

This imports already recorded local data; it does not start devices or collect users.
Metadata must supply the original server word/flash, provenance and known/unknown truth.
"""
import argparse
import base64
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.comparison import DATASET_VERSION, load_dataset


def blob(raw):
    if not isinstance(raw, str):
        raise ValueError('Expected original base64 media')
    if raw.startswith('data:'):
        header, separator, raw = raw.partition(',')
        if not separator or not header.endswith(';base64'):
            raise ValueError('Invalid base64 data URL')
    return base64.b64decode(raw, validate=True)


def export_submissions(events, output):
    """Decode exact collector submissions, including Look-only terminal failures.

    Returns a manifest submission sequence and anonymous recording fingerprints;
    original timestamp numbers/audio offset/media bytes are never repaired.
    """
    from tools.comparison import canonical, digest
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    sequence, records = [], []
    for index, event in enumerate(events):
        stage, payload = event['stage'], event['payload']
        if stage not in ('look', 'speak'):
            raise ValueError('Only original Look/Speak uploads can be exported')
        folder = output / f'{index:02}-{stage}'
        folder.mkdir()
        frames = []
        for n, frame in enumerate(payload['frames']):
            file = folder / f'frame-{n:04}.img'
            file.write_bytes(blob(frame['image']))
            frames.append({'path': file.relative_to(output).as_posix(), 'tMs': frame.get('tMs')})
        submission = {'stage': stage, 'frames': frames}
        original = {'frames': [{'tMs': f.get('tMs'), 'image': base64.b64encode(blob(f['image'])).decode('ascii')}
                               for f in payload['frames']]}
        if stage == 'speak':
            file = folder / 'audio.wav'
            audio = blob(payload['wav'])
            file.write_bytes(audio)
            submission.update(wav=file.relative_to(output).as_posix(), audioStartMs=payload.get('audioStartMs', 0))
            original.update(wav=base64.b64encode(audio).decode('ascii'), audioStartMs=payload.get('audioStartMs', 0))
        sequence.append(submission)
        records.append({'stage': stage, 'sha256': digest(canonical(original))})
    return sequence, records


def import_uploads(look_path, speak_path, enrollment_path, metadata_path, output):
    look = json.loads(Path(look_path).read_text(encoding='utf-8'))
    speak = json.loads(Path(speak_path).read_text(encoding='utf-8'))
    metadata = json.loads(Path(metadata_path).read_text(encoding='utf-8'))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    def frames(payload, stage):
        folder = output / stage
        folder.mkdir()
        result = []
        for index, frame in enumerate(payload['frames']):
            name = f'{stage}/frame-{index:04}.img'
            (output / name).write_bytes(blob(frame['image']))
            result.append({'path': name, 'tMs': frame.get('tMs')})
        return result
    look_frames = frames(look, 'look')
    speak_frames = frames(speak, 'speak')
    (output / 'audio.wav').write_bytes(blob(speak['wav']))
    shutil.copyfile(enrollment_path, output / 'enrollment.img')
    case = {key: metadata[key] for key in ('id', 'fixtureCategory', 'split', 'timingProvenance',
                                         'expectedWord', 'flashStartMs', 'groundTruth')}
    for key in ('source', 'consentRecorded'):
        if key in metadata:
            case[key] = metadata[key]
    case.update(enrollment='reference', attempts=[{'lookFrames': look_frames, 'speakFrames': speak_frames,
                                                 'wav': 'audio.wav', 'audioStartMs': speak.get('audioStartMs', 0)}])
    manifest = {'schemaVersion': DATASET_VERSION, 'datasetId': metadata.get('datasetId', metadata['id']),
                'provenance': {'method': 'Imported original upload JSON; no frame interpolation, timestamp rewriting, resizing, resampling or padding.'},
                'enrollments': {'reference': {'method': 'legacy_single_image', 'path': 'enrollment.img'}}, 'cases': [case]}
    path = output / 'manifest.json'
    path.write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding='utf-8')
    load_dataset(path)  # Structural/provenance checks only; media policy stays in the actual routes.
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--look', type=Path, required=True)
    parser.add_argument('--speak', type=Path, required=True)
    parser.add_argument('--enrollment', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import_uploads(args.look, args.speak, args.enrollment, args.metadata, args.output)
    print('Imported original media bytes and timestamps into a fresh local dataset.')
