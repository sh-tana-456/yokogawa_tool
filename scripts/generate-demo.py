#!/usr/bin/env python3
"""Regenerate public synthetic demo files (MIT), without reading captures."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from yokogawa_tool.core.demo import write_demo

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1]/'demo')
args = parser.parse_args()
write_demo(args.output)
print(f'Wrote six synthetic WVF/HDR pairs to {args.output}')
