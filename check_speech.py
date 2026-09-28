"""Setup check only: local model availability/inference, with no database access."""
import json
import sys
from pathlib import Path

from flask import Flask
from config import Config
from app.services.speech import availability, transcribe
from app.services.voice_detector import read_wav

app = Flask(__name__)
app.config.from_object(Config)
with app.app_context():
    result = availability()
    if result['ok'] and len(sys.argv) == 2:
        samples, rate = read_wav(Path(sys.argv[1]).read_bytes())
        result = transcribe(samples, rate)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['ok'] else 1)
