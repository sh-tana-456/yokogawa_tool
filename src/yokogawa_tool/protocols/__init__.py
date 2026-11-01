"""Protocol decoder dispatch: native EnDat and optional sigrok decoders."""
from .models import Annotation
from .logic import logic_data
from .sigrok import PROTOCOLS as SIGROK_PROTOCOLS, parse_trace_events
from .sigrok import decode as decode_sigrok

PROTOCOLS = {**SIGROK_PROTOCOLS, 'endat': ('clk', 'data')}


def decode(protocol, channels, thresholds, options=None, executable='sigrok-cli'):
    if protocol == 'endat':
        from .endat import decode_endat
        return decode_endat(channels, thresholds, options)
    return decode_sigrok(protocol, channels, thresholds, options, executable)
