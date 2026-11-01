"""Safe array arithmetic and waveform analysis; no eval or executable expressions."""
import ast
import operator
import numpy as np
from yokogawa_tool.core.waveform import Trace


def expression_trace(expression, traces, name="MATH1"):
    if len(expression) > 500:
        raise ValueError("数式は500文字以内で指定してください。")
    tree = ast.parse(expression, mode="eval")
    by_name = {t.name: t for t in traces}
    names = list(dict.fromkeys(n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
                              and n.id not in ("abs", "sqrt", "sin", "cos")))
    if not names or any(n not in by_name for n in names):
        raise ValueError("波形名を指定してください。例: CH1 - CH2（波形名は一覧を参照）")
    base = by_name[names[0]]
    for n in names[1:]:
        t = by_name[n]
        if t.x.shape != base.x.shape or not np.allclose(t.x, base.x, rtol=1e-10, atol=1e-15):
            raise ValueError("Mathで組み合わせる波形には同じ時刻・サンプル数が必要です。")
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow}
    functions = {"abs": np.abs, "sqrt": np.sqrt, "sin": np.sin, "cos": np.cos}

    def run(node):
        if isinstance(node, ast.Expression):
            return run(node.body)
        if isinstance(node, ast.Name) and node.id in by_name:
            return by_name[node.id].y
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            number = float(node.value)
            if not np.isfinite(number) or abs(number) > 1e100:
                raise ValueError("定数が大きすぎます。")
            return number
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            left, right = run(node.left), run(node.right)
            if isinstance(node.op, ast.Pow) and (np.ndim(right) != 0 or abs(right) > 16):
                raise ValueError("指数は-16〜16の定数で指定してください。")
            return ops[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return run(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in functions and len(node.args) == 1 and not node.keywords:
            return functions[node.func.id](run(node.args[0]))
        raise ValueError("使用できる式: 波形名、数値、+ - * / **、abs/sqrt/sin/cos")

    with np.errstate(all="ignore"):
        y = np.broadcast_to(run(tree), base.y.shape).copy()
    y[~np.isfinite(y)] = np.nan
    if not np.any(np.isfinite(y)):
        raise ValueError("演算結果に有効な値がありません。ゼロ除算や定義域を確認してください。")
    return Trace(name, base.x.copy(), y, "arb", "#b59aff", metadata={"expression": expression})


def transform(trace, operation, name, window=11):
    dt = np.diff(trace.x)
    if not np.allclose(dt, dt[0], rtol=1e-5, atol=1e-15):
        raise ValueError("等間隔サンプリングの波形が必要です。")
    if operation == "微分":
        y, unit = np.gradient(trace.y, trace.x), f"{trace.unit}/s"
    elif operation == "積分":
        y = np.r_[0., np.cumsum((trace.y[1:] + trace.y[:-1]) * dt / 2)]
        unit = f"{trace.unit}·s"
    elif operation == "移動平均":
        window = min(int(window), len(trace.y))
        if window < 1:
            raise ValueError("窓幅は1以上が必要です。")
        left = (window - 1) // 2
        y = np.convolve(np.pad(trace.y, (left, window - 1 - left), mode="edge"),
                        np.ones(window) / window, mode="valid")
        unit = trace.unit
    else:
        raise ValueError("未対応の演算です。")
    return Trace(name, trace.x.copy(), y, unit, "#b59aff", metadata={"operation": operation, "source": trace.name})


def spectrum(trace):
    if len(trace.y) < 3:
        raise ValueError("Hann窓のFFTには3サンプル以上が必要です。")
    dt = np.diff(trace.x)
    if not np.allclose(dt, dt[0], rtol=1e-5, atol=1e-15) or not np.all(np.isfinite(trace.y)):
        raise ValueError("FFTには欠損のない等間隔サンプリングの波形が必要です。")
    window = np.hanning(len(trace.y))
    amplitude = abs(np.fft.rfft(trace.y * window)) * 2 / window.sum()
    amplitude[0] /= 2
    if len(trace.y) % 2 == 0:
        amplitude[-1] /= 2
    return np.fft.rfftfreq(len(trace.y), dt[0]), amplitude
