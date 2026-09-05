"""Deterministic synthetic FITS dataset generator for astra tests.

Reusable, seed-driven generator for small synthetic astrophotography
datasets (lights / darks / flats / bias). The astra pipeline can discover
the generated files and group the lights by (EXPTIME, GAIN, FILTER) exactly
like real data. No network, no real star fields, fast (< 5 s for small
sizes), fully reproducible via ``seed``.

The module is intentionally self-contained: it imports numpy and
astropy.io.fits (plus the stdlib). ``scipy.ndimage`` is only imported
lazily inside ``_apply_motion`` when a shift/rotation is injected (scipy is
an astra runtime dependency anyway).

Usage example
-------------
.. code-block:: python

    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))  # tests/ directory
    import synthetic

    dataset = synthetic.generate_dataset(
        root=Path("tmp/astral_synth"),
        n_lights_per_group=3,
        exposures=(15, 60),
        gains=(60,),
        size=(64, 64),
        channels=3,
        seed=42,
    )
    print(dataset.group_map)  # {"15s60": [...], "60s60": [...]}

QF-C scene API (S1-A4) — ground-truth for registration/quality tests:

    scene = synthetic.generate_m13_analog(Path("tmp/m13"), seed=42)
    print(scene.dataset.group_map)   # 4 groups, crowded field
    print(scene.rotation_deg)        # (0.0, 0.3, -0.25, 0.12), frame 0 = reference
    print(scene.group_shifts("60s40"))  # [(0,0), (1.3,-2.1), ...]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from astropy.io import fits

# ── astra header conventions (see astro_process/core/fits_parser.py) ──
# HEADER_ALIASES: exptime -> EXPTIME, gain -> GAIN, filter -> FILTER,
# ccd_temp -> CCD-TEMP, object -> OBJECT, date -> DATE-OBS, offset -> OFFSET
KEY_EXPTIME = "EXPTIME"
KEY_GAIN = "GAIN"
KEY_FILTER = "FILTER"
KEY_CCD_TEMP = "CCD-TEMP"
KEY_OBJECT = "OBJECT"
KEY_DATE_OBS = "DATE-OBS"
KEY_OFFSET = "OFFSET"

DEFAULT_TARGET = "SyntheticTarget"
DEFAULT_TEMP_C = -10.0
DEFAULT_OFFSET = 50
DEFAULT_DATE_OBS = "2026-07-17T23:15:09.123456"

# Directory layout under the dataset root (astra convention, see
# astro_process/agents/calibration.py: "target/darks/" and discovery).
LIGHTS_DIR = "lights"
DARKS_DIR = "darks"
FLATS_DIR = "flats"
BIAS_DIR = "bias"


def group_key(exptime: float, gain: int, filter_name: str | None = None) -> str:
    """Compute the astra group hash for (exptime, gain, filter).

    Mirrors ``astro_process.models.core.compute_group_hash`` without
    importing astro_process: ``"15s60"`` for (15.0, 60, None/"none") and
    ``"60s40_Duo-Band"`` when a filter is present.
    """
    exptime_str = (
        f"{float(exptime):.0f}s" if float(exptime) == int(exptime) else f"{exptime}s"
    )
    gain_str = str(int(gain))
    safe_filter = ""
    if filter_name and str(filter_name).strip().lower() not in ("none", ""):
        safe_filter = str(filter_name).strip().replace(" ", "_")
    if safe_filter:
        return f"{exptime_str}{gain_str}_{safe_filter}"
    return f"{exptime_str}{gain_str}"


@dataclass
class SyntheticDataset:
    """Dataset metadata returned by :func:`generate_dataset`."""

    root: Path
    lights: list[Path] = field(default_factory=list)
    darks: list[Path] = field(default_factory=list)
    flats: list[Path] = field(default_factory=list)
    bias: list[Path] = field(default_factory=list)
    group_map: dict[str, list[Path]] = field(default_factory=dict)

    @property
    def group_keys(self) -> list[str]:
        """Group keys in deterministic (sorted) order."""
        return sorted(self.group_map)


def _mix_seed(seed: int, *parts: int) -> int:
    """Derive a deterministic sub-seed from a base seed and integer parts.

    Uses a simple integer mix so each generated file has its own stable RNG
    stream (adding or reordering files does not change the others).
    """
    value = seed & 0xFFFFFFFF
    for part in parts:
        value = ((value * 0x9E3779B1) ^ (part & 0xFFFFFFFF)) & 0xFFFFFFFF
    return value


def _make_light(
    rng: np.random.RandomState,
    size: tuple[int, int],
    channels: int,
    noise: float,
    *,
    gradient: tuple[float, ...] = (),
    noise_scale: float = 1.0,
    hot_pixels: int = 0,
    cosmic_rays: int = 0,
    star_count: int = 5,
    star_flux_range: tuple[float, float] = (2.0, 6.0),
    star_sigma_range: tuple[float, float] = (0.8, 1.6),
    star_catalog: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None = None,
) -> np.ndarray:
    """Synthetic light frame: background + stars + optional injection.

    With all defaults the generated pixels are byte-identical to the
    pre-QF-C generator (same RNG consumption order, no motion). Optional
    injection, fully seed-deterministic:

    - ``gradient``: polynomial background coefficients (see :func:`_poly2d`).
    - ``star_count``/``star_flux_range``: number of Gaussian "stars" and
      their amplitude range (defaults 5 and (2.0, 6.0) = legacy behavior).
    - ``star_sigma_range``: Gaussian sigma range for the stars (default
      (0.8, 1.6) = legacy behavior; S1-A9: realistic PSFs need wider sigmas).
    - ``star_catalog``: optional fixed ``(cy, cx, amps, sigs)`` arrays drawn
      once by the caller (S1-A9 ``star_field_consistent=True``). When set,
      the per-frame RNG draws for positions/amplitudes/sigmas are skipped so
      every frame of a dither sequence shows the *same* star field (only
      noise/defects vary) — required for star-based registration
      (astroalign). ``None`` = legacy per-frame random stars.
    - ``hot_pixels``/``cosmic_rays``: defect count per frame.
    """
    height, width = size
    background = 100.0
    img = np.full((height, width), background, dtype=np.float64)

    if star_catalog is not None:
        cy, cx, amps, sigs = star_catalog
        for sy, sx, amp, sg in zip(cy, cx, amps, sigs, strict=True):
            y, x = np.ogrid[:height, :width]
            img += amp * np.exp(-((y - sy) ** 2 + (x - sx) ** 2) / (2.0 * sg**2))
    elif height >= 8 and width >= 8:
        for _ in range(star_count):
            cy = rng.randint(height // 4, height - height // 4)
            cx = rng.randint(width // 4, width - width // 4)
            y, x = np.ogrid[:height, :width]
            sigma = rng.uniform(star_sigma_range[0], star_sigma_range[1])
            amp = rng.uniform(star_flux_range[0], star_flux_range[1])
            img += amp * np.exp(-((y - cy) ** 2 + (x - cx) ** 2) / (2.0 * sigma**2))

    # Polynomial background gradient (normalized coords, see _poly2d).
    # Clipped at 0 so a nebula-style emission region only adds light
    # (never darkens pixels below the flat background).
    if gradient:
        y, x = np.ogrid[:height, :width]
        u = (x - (width - 1) / 2) / (width / 2)
        v = (y - (height - 1) / 2) / (height / 2)
        img += np.clip(_poly2d(u, v, gradient), 0.0, None)

    # Even/odd row modulation: deterministic structure, Bayer-friendly.
    img[0::2, :] += 0.5

    noise_sigma = noise_scale * max(noise * background, 0.05)
    img += rng.normal(0.0, noise_sigma, (height, width))
    img = np.clip(img, 0.0, None)

    if hot_pixels:
        img = _inject_hot_pixels(img, rng, hot_pixels)
    if cosmic_rays:
        img = _inject_cosmic_rays(img, rng, cosmic_rays)

    if channels == 1:
        return img.astype(np.float32)  # (H, W) 2D Bayer-friendly

    # Slight per-channel scaling so the channels are not identical.
    factors = np.linspace(0.95, 1.05, channels)
    rgb = np.stack([img * factor for factor in factors], axis=-1)  # (H, W, C)
    return rgb.astype(np.float32).transpose(2, 0, 1)  # (C, H, W)


def _make_dark(rng: np.random.RandomState, size: tuple[int, int]) -> np.ndarray:
    """Synthetic dark frame: dark current + read noise, no signal."""
    height, width = size
    return rng.normal(0.0, 2.0, (height, width)).astype(np.float32)


def _make_flat(size: tuple[int, int]) -> np.ndarray:
    """Synthetic flat frame: bright field with a radial vignette."""
    height, width = size
    y, x = np.ogrid[:height, :width]
    r2 = ((y - (height - 1) / 2) ** 2 + (x - (width - 1) / 2) ** 2) / (
        (max(height, width) / 2) ** 2
    )
    return (200.0 * np.exp(-1.2 * r2) + 20.0).astype(np.float32)


def _make_bias(rng: np.random.RandomState, size: tuple[int, int]) -> np.ndarray:
    """Synthetic bias frame: read noise only, essentially dark."""
    height, width = size
    return rng.normal(0.0, 1.5, (height, width)).astype(np.float32)


def _poly2d(
    u: np.ndarray, v: np.ndarray, coeffs: tuple[float, ...]
) -> np.ndarray:
    """Evaluate a 2D polynomial in normalized coordinates (QF-C gradient).

    ``u``/``v`` must be broadcastable to the frame shape (from ``np.ogrid``:
    ``u`` is the column vector for x, ``v`` the row vector for y). Term
    index ``k`` maps to ``u**i * v**j`` where ``(i, j)`` enumerates
    homogeneous-degree pairs: ``(0,0), (1,0), (0,1), (2,0), (1,1), (0,2),
    (3,0), ...``. With ``coeffs=()`` the result is a zero plane.
    """
    result = np.zeros(np.broadcast(u, v).shape, dtype=np.float64)
    degree = 0
    k = 0
    while k < len(coeffs):
        for i in range(degree, -1, -1):
            j = degree - i
            if k < len(coeffs):
                result = result + coeffs[k] * (u**i) * (v**j)
                k += 1
        degree += 1
    return result


def _inject_hot_pixels(
    img: np.ndarray, rng: np.random.RandomState, count: int
) -> np.ndarray:
    """Inject ``count`` saturated single-pixel defects (deterministic RNG)."""
    height, width = img.shape
    ys = rng.randint(0, height, size=count)
    xs = rng.randint(0, width, size=count)
    img[ys, xs] += 65535.0
    return img


def _inject_cosmic_rays(
    img: np.ndarray, rng: np.random.RandomState, count: int
) -> np.ndarray:
    """Inject ``count`` short high-intensity streaks (deterministic RNG)."""
    height, width = img.shape
    for _ in range(count):
        cy = rng.randint(0, height)
        cx = rng.randint(0, width)
        length = rng.randint(2, 5)
        dy = rng.randint(-1, 2)
        dx = rng.randint(-1, 2)
        while dx == 0 and dy == 0:
            dx = rng.randint(-1, 2)
            dy = rng.randint(-1, 2)
        amp = rng.uniform(200.0, 800.0)
        for step in range(length):
            yy = cy + dy * step
            xx = cx + dx * step
            if 0 <= yy < height and 0 <= xx < width:
                img[yy, xx] += amp * (1.0 - 0.25 * step)
    return img


def _apply_motion(
    data: np.ndarray,
    *,
    shift_y: float,
    shift_x: float,
    angle_deg: float,
    order: int = 1,
    fill: float = 0.0,
    prefilter: bool = False,
) -> np.ndarray:
    """Apply rigid motion: rotation about the frame center, then shift.

    ``scipy.ndimage`` is imported lazily here (scipy is an astra runtime
    dependency). ``shift_y``/``shift_x`` follow scipy axis order
    (rows/y first, cols/x second) — for the astroalign mapping this means
    ``shift_x == T.translation[0]`` and ``shift_y == T.translation[1]``.
    Edge pixels outside the original frame are filled with ``fill``
    (default 0.0 = legacy; S1-A9: ``fill=100.0`` (the flat background)
    avoids the black edge wedges that otherwise show up as artificial
    high-pass sources for star-based registration like astroalign).
    """
    from scipy import ndimage

    ndim = data.ndim
    axes = (ndim - 2, ndim - 1)  # (H, W) for 2D, (H, W) within (C, H, W)
    out = data
    if angle_deg:
        out = ndimage.rotate(
            out, angle_deg, axes=axes, reshape=False, order=order,
            mode="constant", cval=fill, prefilter=prefilter,
        )
    if shift_y or shift_x:
        # ndimage.shift has no axes argument: for (C, H, W) prepend a zero
        # shift so the channel axis is left untouched.
        full_shift = (0.0,) + (shift_y, shift_x) if ndim == 3 else (shift_y, shift_x)
        out = ndimage.shift(
            out, shift=full_shift, order=order,
            mode="constant", cval=fill, prefilter=prefilter,
        )
    return out


def _base_header(
    exptime: float,
    gain: int,
    *,
    object_name: str,
    channels: int,
    filter_name: str | None = None,
) -> dict[str, object]:
    """FITS header keys the astra pipeline reads (fits_parser aliases)."""
    header: dict[str, object] = {
        KEY_EXPTIME: float(exptime),
        KEY_GAIN: int(gain),
        KEY_CCD_TEMP: DEFAULT_TEMP_C,
        KEY_OBJECT: object_name,
        KEY_DATE_OBS: DEFAULT_DATE_OBS,
        KEY_OFFSET: DEFAULT_OFFSET,
    }
    if filter_name:
        header[KEY_FILTER] = filter_name
    if channels > 1:
        header["CTYPE3"] = "RGB"
        header["CUNIT3"] = "channel"
    return header


def _write_fits(path: Path, data: np.ndarray, header: dict[str, object]) -> Path:
    """Write a deterministic FITS file (no timestamps, no network)."""
    hdu = fits.PrimaryHDU(data)
    for key, value in header.items():
        hdu.header[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu.writeto(path, overwrite=True)
    return path


def generate_dataset(
    root: Path,
    *,
    n_lights_per_group: int = 3,
    exposures: tuple[int, ...] = (15, 60),
    gains: tuple[int, ...] = (60,),
    size: tuple[int, int] = (64, 64),
    channels: int = 3,
    seed: int = 42,
    noise: float = 0.01,
    include_darks: bool = True,
    include_flats: bool = True,
    include_bias: bool = True,
    gradient: tuple[float, ...] = (),
    shifts: tuple[tuple[float, float], ...] | None = None,
    rotation_deg: tuple[float, ...] | None = None,
    noise_scale: float = 1.0,
    hot_pixels: int = 0,
    cosmic_rays: int = 0,
    star_count: int = 5,
    star_flux_range: tuple[float, float] = (2.0, 6.0),
    star_sigma_range: tuple[float, float] = (0.8, 1.6),
    star_field_consistent: bool = False,
    star_full_frame: bool = False,
    motion_fill: float = 0.0,
    motion_prefilter: bool = False,
    motion_order: int = 1,
    filter_name: str | None = None,
    object_name: str = DEFAULT_TARGET,
) -> SyntheticDataset:
    """Generate a deterministic synthetic astrophotography dataset.

    Creates FITS files under ``root`` in astra convention subdirectories
    (``lights/``, ``darks/``, ``flats/``, ``bias/``). Groups are the cross
    product of ``exposures`` x ``gains`` (2 groups by default:
    ``"15s60"`` and ``"60s60"`` — the same keys astra computes via
    ``compute_group_hash``).

    QF-C injection (S1-A4) — all optional, defaults reproduce the legacy
    byte-identical output:

    - ``gradient``: polynomial background coefficients in normalized
      coordinates (see :func:`_poly2d`); ``()`` = no gradient.
    - ``shifts``: per-frame ``(shift_y, shift_x)`` in scipy axis order
      (rows/y first, cols/x second), applied to every group identically.
      Length must equal ``n_lights_per_group``; frame 0 is the reference.
    - ``rotation_deg``: per-frame rotation in degrees about the frame
      center (after/before shift: rotation is applied first, then shift).
      Length must equal ``n_lights_per_group``; frame 0 is the reference.
    - ``noise_scale``: multiplier on the Gaussian noise level (1.0 =
      legacy). ``hot_pixels``/``cosmic_rays``: defect count per frame.
    - ``star_count``/``star_flux_range``: star field density (5 and
      (2.0, 6.0) = legacy).
    - ``star_sigma_range``: Gaussian sigma range of the stars (default
      (0.8, 1.6) = legacy; S1-A9: wider PSFs are needed for star-based
      registration like astroalign).
    - ``star_field_consistent``: if True (S1-A9), a fixed star catalog
      (positions/amplitudes/sigmas) is drawn once from a dedicated
      sub-stream and reused for *every* frame of *every* group, so dither
      sequences show the same star field (only noise/defects vary) — the
      prerequisite for astroalign to find point correspondences. ``False``
      = legacy per-frame random stars.
    - ``star_full_frame``: catalog positions span the whole frame
      (20..H-20 / 20..W-20) instead of the legacy central box
      (H/4..3H/4). Only relevant together with ``star_field_consistent``.
      S1-A9 calibration: central placement leaves < 81 detected sources,
      full-frame placement keeps the 81-119 density reference (AC-W9-C7).
    - ``motion_fill``/``motion_prefilter``/``motion_order``: ``cval`` /
      ``prefilter`` / interpolation ``order`` for the rotation+shift
      (defaults 0.0 / False / 1 = legacy). S1-A9: the M13 analog uses
      ``motion_fill=100.0`` (flat background) + ``prefilter=True`` +
      ``motion_order=3`` so the rotated edges stay at background level and
      the cubic interpolation keeps the star centroids stable — black edge
      wedges / bilinear centroid drift would otherwise create artificial
      high-pass sources and sub-pixel bias that degrade star-based
      registration (astroalign).
    - ``filter_name``/``object_name``: FITS ``FILTER``/``OBJECT`` (with a
      filter, group keys get the ``_<filter>`` suffix, e.g. ``Duo-Band``).

    For tests that need the injected ground truth back, prefer
    :func:`generate_scene`, :func:`generate_m13_analog` or
    :func:`generate_m27_analog` (returns :class:`SyntheticScene`).

    Args:
        root: Dataset directory; subdirectories are created as needed.
        n_lights_per_group: Number of light frames per group.
        exposures: Exposure times in seconds (FITS ``EXPTIME``).
        gains: Sensor gains (FITS ``GAIN``).
        size: ``(height, width)`` — both sides must be even (Bayer-friendly).
        channels: Number of image channels (3 => RGB (C, H, W) FITS,
            1 => 2D (H, W)).
        seed: Random seed; same seed produces byte-identical files.
        noise: Relative Gaussian noise level applied to light backgrounds.
        include_darks: Create one dark per group.
        include_flats: Create one flat.
        include_bias: Create one bias.

    Returns:
        :class:`SyntheticDataset` with all created file paths and the
        group map (group key -> light paths).
    """
    root = Path(root)
    if len(size) != 2 or size[0] <= 0 or size[1] <= 0:
        raise ValueError(f"size must be a positive (height, width) tuple, got {size!r}")
    if size[0] % 2 != 0 or size[1] % 2 != 0:
        raise ValueError(f"size must have even sides (Bayer-friendly), got {size!r}")
    if channels < 1:
        raise ValueError(f"channels must be >= 1, got {channels!r}")
    if star_count < 0:
        raise ValueError(f"star_count must be >= 0, got {star_count!r}")
    if len(star_flux_range) != 2 or star_flux_range[0] <= 0 or star_flux_range[1] < star_flux_range[0]:
        raise ValueError(
            f"star_flux_range must be (min, max) with 0 < min <= max, got {star_flux_range!r}"
        )
    if len(star_sigma_range) != 2 or star_sigma_range[0] <= 0 or star_sigma_range[1] < star_sigma_range[0]:
        raise ValueError(
            f"star_sigma_range must be (min, max) with 0 < min <= max, got {star_sigma_range!r}"
        )
    if hot_pixels < 0:
        raise ValueError(f"hot_pixels must be >= 0, got {hot_pixels!r}")
    if cosmic_rays < 0:
        raise ValueError(f"cosmic_rays must be >= 0, got {cosmic_rays!r}")

    if shifts is not None:
        shifts = tuple((float(sy), float(sx)) for sy, sx in shifts)
        if len(shifts) != n_lights_per_group:
            raise ValueError(
                f"shifts length {len(shifts)} != n_lights_per_group {n_lights_per_group}"
            )
    else:
        shifts = ()
    if rotation_deg is not None:
        rotation_deg = tuple(float(r) for r in rotation_deg)
        if len(rotation_deg) != n_lights_per_group:
            raise ValueError(
                f"rotation_deg length {len(rotation_deg)} != n_lights_per_group "
                f"{n_lights_per_group}"
            )
    else:
        rotation_deg = ()

    light_dir = root / LIGHTS_DIR
    dark_dir = root / DARKS_DIR
    flat_dir = root / FLATS_DIR
    bias_dir = root / BIAS_DIR

    lights: list[Path] = []
    darks: list[Path] = []
    flats: list[Path] = []
    bias: list[Path] = []
    group_map: dict[str, list[Path]] = {}

    groups = [(float(exptime), int(gain)) for exptime in exposures for gain in gains]

    # S1-A9: fixed star catalog for star_field_consistent=True — drawn once
    # from a dedicated sub-stream so frame RNGs stay untouched (determinism
    # and legacy byte-identity preserved).
    star_catalog: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None = None
    if star_field_consistent and star_count > 0:
        rng_cat = np.random.RandomState(_mix_seed(seed, 77_777))
        height, width = size
        if star_full_frame:
            cy = rng_cat.randint(20, height - 20, star_count)
            cx = rng_cat.randint(20, width - 20, star_count)
        else:
            cy = rng_cat.randint(height // 4, height - height // 4, star_count)
            cx = rng_cat.randint(width // 4, width - width // 4, star_count)
        amps = rng_cat.uniform(star_flux_range[0], star_flux_range[1], star_count)
        sigs = rng_cat.uniform(star_sigma_range[0], star_sigma_range[1], star_count)
        star_catalog = (cy.astype(np.float64), cx.astype(np.float64),
                        amps.astype(np.float64), sigs.astype(np.float64))

    for group_idx, (exptime, gain) in enumerate(groups):
        key = group_key(exptime, gain, filter_name)
        group_lights: list[Path] = []
        for frame_idx in range(n_lights_per_group):
            rng = np.random.RandomState(_mix_seed(seed, group_idx, frame_idx))
            data = _make_light(
                rng, size, channels, noise,
                gradient=gradient, noise_scale=noise_scale,
                hot_pixels=hot_pixels, cosmic_rays=cosmic_rays,
                star_count=star_count, star_flux_range=star_flux_range,
                star_sigma_range=star_sigma_range, star_catalog=star_catalog,
            )
            if shifts or rotation_deg:
                shift_y, shift_x = shifts[frame_idx] if shifts else (0.0, 0.0)
                angle = rotation_deg[frame_idx] if rotation_deg else 0.0
                data = _apply_motion(
                    data, shift_y=shift_y, shift_x=shift_x, angle_deg=angle,
                    fill=motion_fill, prefilter=motion_prefilter, order=motion_order,
                ).astype(np.float32, copy=False)
            path = _write_fits(
                light_dir / f"light_{key}_{frame_idx + 1:04d}.fits",
                data,
                _base_header(
                    exptime, gain, object_name=object_name, channels=channels,
                    filter_name=filter_name,
                ),
            )
            group_lights.append(path)
        lights.extend(group_lights)
        group_map[key] = group_lights

        if include_darks:
            rng = np.random.RandomState(_mix_seed(seed, 10_000 + group_idx))
            path = _write_fits(
                dark_dir / f"dark_{key}.fits",
                _make_dark(rng, size),
                _base_header(exptime, gain, object_name="SyntheticDark", channels=1),
            )
            darks.append(path)

    if include_flats and groups:
        exptime, gain = groups[0]
        path = _write_fits(
            flat_dir / "flat.fits",
            _make_flat(size),
            _base_header(exptime, gain, object_name="SyntheticFlat", channels=1),
        )
        flats.append(path)

    if include_bias and groups:
        rng = np.random.RandomState(_mix_seed(seed, 20_000))
        exptime, gain = groups[0]
        path = _write_fits(
            bias_dir / "bias.fits",
            _make_bias(rng, size),
            _base_header(exptime, gain, object_name="SyntheticBias", channels=1),
        )
        bias.append(path)

    return SyntheticDataset(
        root=root,
        lights=lights,
        darks=darks,
        flats=flats,
        bias=bias,
        group_map=group_map,
    )


@dataclass
class SyntheticScene:
    """Ground-truth wrapper for injected QF-C scenes (AC-QF-C3).

    Returned by :func:`generate_scene`, :func:`generate_m13_analog` and
    :func:`generate_m27_analog`. Carries the injected parameters next to
    the generated :class:`SyntheticDataset` so tests can assert exact
    expectations (shift / rotation / gradient / ...) ± tolerance.
    """

    dataset: SyntheticDataset
    seed: int = 42
    shifts: tuple[tuple[float, float], ...] = ()
    rotation_deg: tuple[float, ...] = ()
    gradient: tuple[float, ...] = ()
    noise_scale: float = 1.0
    hot_pixels: int = 0
    cosmic_rays: int = 0
    star_count: int = 5
    star_flux_range: tuple[float, float] = (2.0, 6.0)
    filter_name: str | None = None
    object_name: str = DEFAULT_TARGET

    @property
    def root(self) -> Path:
        """Dataset root directory."""
        return self.dataset.root

    def group_shifts(self, group_key: str) -> list[tuple[float, float]]:
        """Ground-truth per-frame shifts for one group (frame 0 = reference).

        The motion pattern is applied identically to every group, so the
        value only depends on ``group_key`` via validation.
        """
        return list(self.shifts)

    def group_rotation_deg(self, group_key: str) -> list[float]:
        """Ground-truth per-frame rotation for one group (frame 0 = reference)."""
        return list(self.rotation_deg)


def generate_scene(
    root: Path,
    *,
    n_lights_per_group: int = 3,
    exposures: tuple[int, ...] = (15, 60),
    gains: tuple[int, ...] = (60,),
    size: tuple[int, int] = (64, 64),
    channels: int = 3,
    seed: int = 42,
    noise: float = 0.01,
    include_darks: bool = True,
    include_flats: bool = True,
    include_bias: bool = True,
    gradient: tuple[float, ...] = (),
    shifts: tuple[tuple[float, float], ...] | None = None,
    rotation_deg: tuple[float, ...] | None = None,
    noise_scale: float = 1.0,
    hot_pixels: int = 0,
    cosmic_rays: int = 0,
    star_count: int = 5,
    star_flux_range: tuple[float, float] = (2.0, 6.0),
    star_sigma_range: tuple[float, float] = (0.8, 1.6),
    star_field_consistent: bool = False,
    star_full_frame: bool = False,
    motion_fill: float = 0.0,
    motion_prefilter: bool = False,
    motion_order: int = 1,
    filter_name: str | None = None,
    object_name: str = DEFAULT_TARGET,
) -> SyntheticScene:
    """Like :func:`generate_dataset` but returns the ground-truth scene.

    Same parameters and defaults as :func:`generate_dataset`; the returned
    :class:`SyntheticScene` wraps the dataset and the injected parameters
    (shifts / rotation / gradient / ...) for exact test assertions.
    """
    dataset = generate_dataset(
        root,
        n_lights_per_group=n_lights_per_group,
        exposures=exposures,
        gains=gains,
        size=size,
        channels=channels,
        seed=seed,
        noise=noise,
        include_darks=include_darks,
        include_flats=include_flats,
        include_bias=include_bias,
        gradient=gradient,
        shifts=shifts,
        rotation_deg=rotation_deg,
        noise_scale=noise_scale,
        hot_pixels=hot_pixels,
        cosmic_rays=cosmic_rays,
        star_count=star_count,
        star_flux_range=star_flux_range,
        star_sigma_range=star_sigma_range,
        star_field_consistent=star_field_consistent,
        star_full_frame=star_full_frame,
        motion_fill=motion_fill,
        motion_prefilter=motion_prefilter,
        motion_order=motion_order,
        filter_name=filter_name,
        object_name=object_name,
    )
    return SyntheticScene(
        dataset=dataset,
        seed=seed,
        shifts=() if shifts is None else tuple((float(sy), float(sx)) for sy, sx in shifts),
        rotation_deg=() if rotation_deg is None else tuple(float(r) for r in rotation_deg),
        gradient=tuple(gradient),
        noise_scale=noise_scale,
        hot_pixels=hot_pixels,
        cosmic_rays=cosmic_rays,
        star_count=star_count,
        star_flux_range=tuple(star_flux_range),
        filter_name=filter_name,
        object_name=object_name,
    )


def generate_m13_analog(
    root: Path,
    *,
    seed: int = 42,
    size: tuple[int, int] = (384, 384),
    n_lights_per_group: int = 4,
    star_count: int = 120,
    star_flux_range: tuple[float, float] = (60.0, 400.0),
    star_sigma_range: tuple[float, float] = (1.2, 2.0),
    star_field_consistent: bool = True,
    star_full_frame: bool = True,
    motion_fill: float = 100.0,
    motion_prefilter: bool = True,
    motion_order: int = 3,
) -> SyntheticScene:
    """Crowded-field analog of the M13 real dataset (AC-QF-C4 / AC-W9-C7).

    4 groups with mixed exposures/gains (15s60 / 15s40 / 60s60 / 60s40),
    ``star_count=120`` point sources spanning the full frame → 81–119
    sources > 12·MAD per frame (stella density reference, AC-W9-C7),
    per-frame translation + rotation with frame 0 as reference. Mono
    (channels=1).

    S1-A9 calibration (seed 42, 384x384, verified):
    - ``star_field_consistent=True`` + ``star_full_frame=True``: a fixed
      star catalog is drawn once and reused for every frame, so astroalign
      finds 49-50/50 control points and recovers the injected rotation /
      scale / translation within tolerance (the old per-frame random stars
      made astroalign impossible — each frame showed a different field).
    - ``star_flux_range`` (60.0, 400.0) and ``star_sigma_range`` (1.2,
      2.0) keep the density in [81, 119] (S1-A8-Befund: 8–30 too weak on
      the 100-ADU background — RANSAC ran empty; S1-A9 calibration: at
      60–250 the pipeline arbitration still downgrades astroalign
      (corr_hp_aa ~0.82 < corr_hp_fft - 0.05, black apply-transform
      edges), at 60–400 astroalign wins on every frame and recovers the
      GT).
    - ``motion_fill=100.0`` / ``motion_prefilter=True`` /
      ``motion_order=3``: rotated edges stay at background level and the
      cubic interpolation keeps star centroids stable — black edge wedges
      / bilinear centroid drift would otherwise bias star-based
      registration (astroalign).
    - The injected motion follows ``scipy.ndimage``: rotate by ``+angle``
      about the frame center, then shift by ``s``. The astroalign
      translation therefore equals ``C - R(-angle) @ (C + s)`` (not the
      raw shift ``s``) — tests use this formula for the expected value.
    - Pass ``star_field_consistent=False`` +
      ``star_flux_range=(8.0, 30.0)`` + ``motion_fill=0.0`` /
      ``motion_order=1`` explicitly to exercise the astroalign fallback
      chain (weak stars, no stable field → MaxIterError → fft).
    """
    return generate_scene(
        root,
        n_lights_per_group=n_lights_per_group,
        exposures=(15, 60),
        gains=(60, 40),
        size=size,
        channels=1,
        seed=seed,
        noise=0.003,
        star_count=star_count,
        star_flux_range=star_flux_range,
        star_sigma_range=star_sigma_range,
        star_field_consistent=star_field_consistent,
        star_full_frame=star_full_frame,
        motion_fill=motion_fill,
        motion_prefilter=motion_prefilter,
        motion_order=motion_order,
        shifts=(
            (0.0, 0.0),
            (1.3, -2.1),
            (-0.8, 1.6),
            (2.1, 0.4),
        ),
        rotation_deg=(0.0, 0.3, -0.25, 0.12),
    )


def generate_m27_analog(
    root: Path,
    *,
    seed: int = 42,
    size: tuple[int, int] = (256, 256),
    n_lights_per_group: int = 4,
) -> SyntheticScene:
    """Duo-Band nebula analog of the M27 real dataset (AC-QF-C4, S1-A1).

    ``FILTER="Duo-Band"`` (group key ``"30s40_Duo-Band"``), OBJECT
    ``"M 27"``, a soft polynomial emission region (nebula glow), a narrow
    star population plus a few hot pixels / cosmic rays, per-frame
    translation with frame 0 as reference (no rotation). Mono (channels=1).
    """
    return generate_scene(
        root,
        n_lights_per_group=n_lights_per_group,
        exposures=(30,),
        gains=(40,),
        size=size,
        channels=1,
        seed=seed,
        noise=0.004,
        filter_name="Duo-Band",
        object_name="M 27",
        # Degree-4 polynomial in normalized coords (terms k=0..14 per
        # _poly2d: (0,0),(1,0),(0,1),(2,0),(1,1),(0,2),...,(4,0),...,(0,4)),
        # clipped at 0: a localized soft emission glow peaking at ~12 ADU
        # near (u=0.15, v=-0.16) → 100 + [0 .. 12] over ~30% of the frame
        # (diffuse nebula), corners stay at the flat background.
        gradient=(12.0, 3.0, -2.0, -10.0, 0.0, -6.0, 0.0, 0.0, 0.0, 0.0,
                  -12.0, 0.0, 0.0, 0.0, -12.0),
        star_count=8,
        star_flux_range=(4.0, 12.0),
        hot_pixels=4,
        cosmic_rays=3,
        shifts=(
            (0.0, 0.0),
            (1.8, -0.7),
            (-1.2, 1.4),
            (0.5, -2.0),
        ),
    )


def generate_az_field_rotation_analog(
    root: Path,
    *,
    seed: int = 42,
    size: tuple[int, int] = (384, 384),
    n_lights_per_group: int = 4,
) -> SyntheticScene:
    """AZ-Feldrotations-Analog (UGC-10822-Motiv, AC-RE-F1/AC-RE-F2).

    Reproduziert das RE-F-Beleg-Szenario (RE-F, V1.3-24): ein Duo-Band-Target
    auf einer AZ-Montierung mit langsam kumulierender Feldrotation ueber die
    Frames. Kalibriert (Seed 42, 384x384, seed=42):

    - ``FILTER="Duo-Band"`` / ``OBJECT="UGC 10822"`` (Galaxie statt Nebel —
      das Signal ist stern-dominiert, kein diffuses Band).
    - ``star_count=16``, ``star_flux_range=(80.0, 220.0)``,
      ``star_sigma_range=(1.4, 2.0)``: moderates konsistentes Sternfeld
      (``star_field_consistent=True`` + ``star_full_frame=True``), das
      astroalign kontrollpunkt-faehig macht, aber die Hochpass-Korrelation
      bleibt moderat (corr_hp_aa ~0.43-0.48 auf 384x384).
    - ``rotation_deg=(0.0, 1.9, -1.8, 1.7)``: Feldrotation, die pro Frame
      die SanityGuard-Grenze (Default 2.0 Grad) NICHT ueberschreitet
      (AC-RE-F2: der Guard darf nicht mit dem SanityGuard kollidieren).
    - Subpixel-Shifts (0.3, -0.7) etc.: fft auf dem Integer-Grid verfehlt
      die Subpixel-Komponente, astroalign gewinnt die Arbitration
      (W9-C) auf jedem Frame (keine Downgrades bei Default-Schwelle 0.05,
      V19-FIX-12).

    W1-Guard-Verhalten (RE-F) auf dieser Szene:
    - Default ``zero_shift_threshold=0.05`` (V19-FIX-12 P1 Mandatory Gate):
      corr_hp_aa ~0.43-0.48 > 0.05 -> astroalign registriert normal (kein
      Reject).
    - ``zero_shift_threshold=0.5``: corr_hp_aa < 0.5 -> JEDER Nicht-Referenz-
      Frame wird verworfen (``registration.frame_rejected``,
      len(registered) == 1 = nur Referenz) — die kalibrierte Schwelle
      erzeugt den RE-F-Reject deterministisch.

    Verwendung (Muster test_registration.py):
        pytest.importorskip("astroalign")
        scene = synthetic.generate_az_field_rotation_analog(tmp_path / "az")
        group = next(iter(scene.dataset.group_map.values()))
    """
    return generate_scene(
        root,
        n_lights_per_group=n_lights_per_group,
        exposures=(30,),
        gains=(40,),
        size=size,
        channels=1,
        seed=seed,
        noise=0.004,
        filter_name="Duo-Band",
        object_name="UGC 10822",
        star_count=16,
        star_flux_range=(80.0, 220.0),
        star_sigma_range=(1.4, 2.0),
        star_field_consistent=True,
        star_full_frame=True,
        motion_fill=100.0,
        motion_prefilter=True,
        motion_order=3,
        shifts=(
            (0.0, 0.0),
            (0.3, -0.7),
            (-0.4, 0.6),
            (0.5, -0.3),
        ),
        rotation_deg=(0.0, 1.9, -1.8, 1.7),
    )


__all__ = [
    "SyntheticDataset",
    "SyntheticScene",
    "generate_dataset",
    "generate_scene",
    "generate_m13_analog",
    "generate_m27_analog",
    "generate_az_field_rotation_analog",
    "group_key",
    "KEY_EXPTIME",
    "KEY_GAIN",
    "KEY_FILTER",
    "KEY_CCD_TEMP",
    "KEY_OBJECT",
    "KEY_DATE_OBS",
    "KEY_OFFSET",
]
