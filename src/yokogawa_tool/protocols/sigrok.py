"""File-only interface to the external sigrok-cli decoder engine."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from .models import Annotation
from .logic import logic_data

PROTOCOLS = {'uart': ('rx',), 'spi': ('clk', 'mosi', 'miso', 'cs'),
             'i2c': ('scl', 'sda'), 'can': ('can_rx',)}
REQUIRED = {'uart': ('rx',), 'spi': ('clk',), 'i2c': ('scl', 'sda'), 'can': ('can_rx',)}
ANNOTATIONS = {'uart': 'rx-data:rx-warnings:rx-parity-err:rx-break',
    'spi': 'mosi-data:miso-data:warnings',
    'i2c': 'start:repeat-start:stop:ack:nack:address-read:address-write:data-read:data-write:warnings',
    'can': 'data:sof:eof:id:ext-id:full-id:dlc:crc-sequence:ack-slot:warnings'}


def external_environment():
    """System sigrok must use OS libraries, rather than frozen Qt's copies."""
    if not (getattr(sys, 'frozen', False) and sys.platform.startswith('linux')):
        return None
    environment = os.environ.copy()
    original = environment.pop('LD_LIBRARY_PATH_ORIG', None)
    if original is None:
        environment.pop('LD_LIBRARY_PATH', None)
    else:
        environment['LD_LIBRARY_PATH'] = original
    return environment


def parse_trace_events(output, scale, origin):
    result, pending = [], {}
    for event in json.loads(output)['traceEvents']:
        key = (event.get('pid'), event.get('tid'))
        if event.get('ph') == 'B':
            pending.setdefault(key, []).append(event)
        elif event.get('ph') == 'E' and pending.get(key):
            start = pending[key].pop()
            result.append(Annotation(origin + float(start['ts'])*scale,
                origin + float(event['ts'])*scale, str(start.get('tid', '')), str(start.get('name', ''))))
    return sorted(result, key=lambda event: (event.start, event.end, event.kind))


def decode(protocol, channels, thresholds, options=None, executable='sigrok-cli'):
    if protocol not in PROTOCOLS or set(channels) - set(PROTOCOLS[protocol]):
        raise ValueError('未対応のプロトコルまたは信号名です。')
    if not set(REQUIRED[protocol]) <= set(channels):
        raise ValueError('必要な信号CHが選択されていません。')
    if protocol == 'spi' and not {'mosi', 'miso'} & set(channels):
        raise ValueError('SPIにはMOSIまたはMISOのCHが必要です。')
    options = dict(options or {})
    if set(options) & set(PROTOCOLS[protocol]):
        raise ValueError('信号の割当はCH選択で指定してください。')
    for key, value in options.items():
        if not re.fullmatch(r'[a-z][a-z0-9_]*', key) or not re.fullmatch(r'[a-zA-Z0-9_.+\-]+', str(value)):
            raise ValueError('復号オプションの書式が不正です。')
    tool = shutil.which(executable)
    if tool is None:
        raise ValueError('sigrok-cliが見つかりません。sigrok-cliとlibsigrokdecodeを導入し、実行ファイルを指定してください。')
    data, dt, origin = logic_data(channels, thresholds)
    samplerate = round(1/dt)
    if samplerate < 1:
        raise ValueError('サンプリングレートが低すぎます。')
    assignments = [f'{role}={bit}' for bit, role in enumerate(channels)]
    arguments = ':'.join([protocol] + assignments + [f'{key}={value}' for key, value in options.items()])
    with tempfile.TemporaryDirectory(prefix='yokogawa-decode-') as directory:
        source = Path(directory) / 'logic.bin'
        source.write_bytes(data.tobytes())
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                process = subprocess.run([tool, '-i', str(source), '-I', f'binary:numchannels=8:samplerate={samplerate}',
                    '-P', arguments, '-A', protocol + '=' + ANNOTATIONS[protocol],
                    '--protocol-decoder-jsontrace', '-l', '1'],
                    stdout=stdout, stderr=stderr, timeout=30, check=False, env=external_environment())
            except subprocess.TimeoutExpired as exc:
                raise ValueError('復号が30秒以内に完了しませんでした。短い記録で再試行してください。') from exc
            stderr.seek(0)
            errors = stderr.read(8192).decode('utf-8', errors='replace')
            if process.returncode or 'LIBUSB_ERROR' in errors:
                raise ValueError('復号エンジンの実行に失敗しました: ' + errors)
            if stdout.tell() > 32 * 1024 * 1024:
                raise ValueError('復号結果が多すぎます。短い記録で再試行してください。')
            stdout.seek(0)
            output = stdout.read().decode('utf-8', errors='replace')
    return parse_trace_events(output, dt * samplerate / 1e6, origin)
