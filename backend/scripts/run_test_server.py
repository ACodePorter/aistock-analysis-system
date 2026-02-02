#!/usr/bin/env python
import sys
import argparse
import uvicorn

# Ensure backend package import works when running from repo root or backend/
sys.path.insert(0, '.')

parser = argparse.ArgumentParser(description='Run test server for AIStock backend')
parser.add_argument('--host', default='0.0.0.0')
parser.add_argument('--port', type=int, default=8080)
parser.add_argument('--lifespan', choices=['on', 'off'], default='off', help='uvicorn lifespan setting')
args = parser.parse_args()

# Import FastAPI app
try:
    from app.main import app
except Exception:
    # fallback if called from repo root
    from backend.app.main import app

uvicorn.run(app, host=args.host, port=args.port, reload=False, log_level='info', lifespan=(None if args.lifespan == 'on' else 'off'))
