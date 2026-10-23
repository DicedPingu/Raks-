import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = os.path.join(ROOT, "host")
if HOST not in sys.path:
    sys.path.insert(0, HOST)
