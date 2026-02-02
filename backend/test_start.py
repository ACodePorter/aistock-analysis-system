#!/usr/bin/env python
import sys
import time
import subprocess
import threading

sys.path.insert(0, ".")

# Try direct import first
print("Attempting to import app.main...")
try:
    from app.main import app
    print("✅ app.main imported successfully")
except Exception as e:
    print(f"❌ Failed to import: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Start server
print("\nStarting Uvicorn server on port 8083...")
import uvicorn
# Run without Lifespan handling to avoid executing FastAPI startup/shutdown hooks
# (prevents scheduler and heavy background tasks from starting during quick tests)
uvicorn.run(app, host="0.0.0.0", port=8083, reload=False, log_level="info", lifespan="off")
