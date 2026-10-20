"""Ponto de entrada do Passenger (cPanel > Setup Python App)."""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from run import app as application  # noqa: E402,F401
