"""Deterministic synthetic WVF fixtures; no instrument or personal data."""
from pathlib import Path
import numpy as np

CONFIGURATIONS = (
    (('CH1', 'CH2', 'CH3'), 1e-6, -.005),
    (('CH1', 'CH2', 'CH3'), 2e-6, -.01),
    (('CH2', 'CH3'), 2e-6, -.01),
    (('CH1', 'CH2', 'CH3'), 1e-7, -.0005),
    (('CH2',), 1e-6, -.005),
    (('CH2',), 2e-6, -.01),
)


def write_demo(directory):
    """Write independently specified IS2/Big/Trace fixtures and their headers."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    scale, length = 1.6276042e-4, 10020
    for index, (names, dt, t0) in enumerate(CONFIGURATIONS):
        x = t0 + np.arange(length)*dt
        angle = 2*np.pi*1000*x
        signals = {'CH1': 1.5 + .9*np.sin(angle),
                   'CH2': 1 + .7*np.cos(angle),
                   'CH3': .2 + 2*(np.sin(angle) >= 0)}
        raw = b''.join(np.rint(signals[name]/scale).astype('>i2').tobytes() for name in names)
        fields = dict(TraceNumber=[len(names)], BlockNumber=[1], TraceName=names,
                      BlockSize=[length]*len(names), VResolution=[scale]*len(names),
                      VOffset=[0]*len(names), VDataType=['IS2']*len(names),
                      VUnit=['V']*len(names), HUnit=['s']*len(names),
                      HResolution=[dt]*len(names), HOffset=[t0]*len(names),
                      VIllegalData=[32767]*len(names))
        header = ('$PublicInfo\nEndian Big\nDataFormat Trace\nDataOffset 0\n'
                  f'GroupNumber 1\nTraceTotalNumber {len(names)}\nModel SYNTHETIC\n$Group1\n')
        header += ''.join(key+' '+' '.join(map(str, values))+'\n' for key, values in fields.items())
        (directory/f'{index:04}.HDR').write_text(header, encoding='ascii')
        (directory/f'{index:04}.WVF').write_bytes(raw)
