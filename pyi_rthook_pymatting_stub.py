"""PyInstaller runtime hook — stub out pymatting so rembg imports without it.

Why: rembg/bg.py imports three pymatting symbols at module top level::

    from pymatting.alpha.estimate_alpha_cf import estimate_alpha_cf
    from pymatting.foreground.estimate_foreground_ml import estimate_foreground_ml
    from pymatting.util.util import stack_images

That import pulls in numba -> llvmlite (~102 MB uncompressed; ~30-45 MB of the
installer). KStudio's background removal (누끼) only calls
``remove(img, session=...)`` with NO ``alpha_matting`` argument, so those three
symbols are imported but never *called*. So we exclude the real
pymatting/numba/llvmlite from the bundle (see KStudio.spec ``excludes``) and
satisfy the top-level import here with lightweight stubs.

Scope: this hook runs ONLY inside the frozen build (PyInstaller ``runtime_hooks``),
before any rembg import. In a dev checkout the real pymatting is used unchanged.

Coupling: this matches rembg/bg.py's exact import list. If a rembg upgrade
imports a new pymatting symbol, the frozen app would fail the moment 누끼 runs —
so the build-time 누끼 smoke test MUST stay a release gate. If alpha matting is
ever requested (KStudio never does), the stub raises a clear NotImplementedError
instead of silently misbehaving.
"""
import sys
import types


def _alpha_matting_disabled(*args, **kwargs):
    raise NotImplementedError(
        "alpha matting is disabled in this KStudio build "
        "(pymatting excluded to reduce installer size)"
    )


def _install_pymatting_stub() -> None:
    if "pymatting" in sys.modules:
        return  # real pymatting already present (e.g. not actually excluded)

    def _pkg(name: str) -> types.ModuleType:
        m = types.ModuleType(name)
        m.__path__ = []  # mark as a package so submodule lookups resolve
        sys.modules[name] = m
        return m

    def _mod(name: str, **attrs) -> types.ModuleType:
        m = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(m, key, value)
        sys.modules[name] = m
        return m

    pm = _pkg("pymatting")
    alpha = _pkg("pymatting.alpha")
    foreground = _pkg("pymatting.foreground")
    util = _pkg("pymatting.util")
    pm.alpha, pm.foreground, pm.util = alpha, foreground, util

    alpha.estimate_alpha_cf = _mod(
        "pymatting.alpha.estimate_alpha_cf",
        estimate_alpha_cf=_alpha_matting_disabled,
    )
    foreground.estimate_foreground_ml = _mod(
        "pymatting.foreground.estimate_foreground_ml",
        estimate_foreground_ml=_alpha_matting_disabled,
    )
    util.util = _mod(
        "pymatting.util.util",
        stack_images=_alpha_matting_disabled,
    )


_install_pymatting_stub()
