"""Explicit local build; never run automatically by a model tool."""
import subprocess
from pathlib import Path

source = Path(__file__).resolve().parent
root = source.parents[1]
output = root / '.aion' / 'bin' / 'aion-reminders'
output.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(['xcrun', 'swiftc', '-target', 'arm64-apple-macosx14.0',
                str(source / 'main.swift'), '-o', str(output),
                '-Xlinker', '-sectcreate', '-Xlinker', '__TEXT', '-Xlinker', '__info_plist',
                '-Xlinker', str(source / 'Info.plist')], check=True)
print('Built local Aion Reminders helper (macOS Apple Silicon).')
