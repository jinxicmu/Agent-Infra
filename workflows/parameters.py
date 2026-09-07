"""Shared, CPU-only request policy and source-compatible canvas/frame calculation."""
import json
import math
from pathlib import Path

POLICY = json.loads((Path(__file__).with_name('PRESETS.json')).read_text())['MiniMax-H3']
DEFAULTS = POLICY['defaults']


class ParameterError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def validate_parameters(resolution, ratio, duration):
    if resolution not in POLICY['resolutions']:
        raise ParameterError('UNSUPPORTED_RESOLUTION')
    if type(duration) is not int or str(duration) not in POLICY['durations']:
        raise ParameterError('UNSUPPORTED_DURATION')
    if ratio not in POLICY['ratio_policy']['fl2v']['allowed']:
        raise ParameterError('INVALID_RATIO_FOR_WORKFLOW')


def frame_count(duration):
    frames = max(5, round(duration * 24))
    return frames + (5 - frames % 17) % 17


def canvas(resolution, ratio, image_size=None):
    if ratio == 'adaptive':
        if image_size is None:
            return None
        w, h = image_size
        if min(w, h) <= 0 or not 0.25 <= w / h <= 4:
            raise ParameterError('INVALID_RATIO_FOR_WORKFLOW')
    else:
        w, h = map(int, ratio.split(':'))
    # Same total-pixel calculation and rounding as the source ResolutionSelector.
    preset = POLICY['resolutions'][resolution]
    area = preset['megapixels'] * 1024 * 1024
    multiple = preset['resolution_steps']
    return (max(multiple, round(math.sqrt(area * w / h) / multiple) * multiple),
            max(multiple, round(math.sqrt(area * h / w) / multiple) * multiple))


def validate_output(output, resolution, ratio, duration):
    validate_parameters(resolution, ratio, duration)
    w, h = output['width'], output['height']
    if (type(w) is not int or type(h) is not int or min(w, h) < 32 or
            max(w, h) > 4096 or w % 32 or h % 32):
        raise ValueError('Invalid output canvas')
    expected = canvas(resolution, ratio)
    if expected is not None and (w, h) != expected:
        raise ValueError('Output canvas differs from request')
    if expected is None:
        area = POLICY['resolutions'][resolution]['megapixels'] * 1024 * 1024
        if not 0.25 <= w / h <= 4 or abs(w * h - area) > 32 * (w + h):
            raise ValueError('Adaptive output exceeds profile budget')
    if output['fps'] != 24 or output['frame_count'] != frame_count(duration):
        raise ValueError('Output frame count differs from request')
    seconds = output['duration_seconds']
    if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or abs(seconds - output['frame_count'] / 24) > .1:
        raise ValueError('Invalid output duration')
