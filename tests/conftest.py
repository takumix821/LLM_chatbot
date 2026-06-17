import sys
import os

# Resolve paths
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Add paths to sys.path to ensure test execution resolves imports correctly
if src_path not in sys.path:
    sys.path.insert(0, src_path)

if root_path not in sys.path:
    sys.path.insert(1, root_path)
