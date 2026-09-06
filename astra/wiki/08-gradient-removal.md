# Gradient Removal

> Extracted from `src/astro_process/core/gradient_removal.py` and `config/models.py GradientRemovalConfig`.

---

Gradient removal — polynomial background modelling for stacked frames.

| Symbol | Kind | Description |
| --- | --- | --- |
| `GradientRemovalError` | class | — |
| `GradientModel` | class | — |
| `GradientRemovalResult` | class | — |
| `fit_background` | function | Fit a polynomial background model with iterative rejection. |
| `remove_gradient` | function | Remove a smooth background gradient from a 2D or RGB frame. |
| `shape_str` | function | — |
| `background_extraction` | function | Apply gradient removal to the stacked frame. |

## GradientRemovalConfig

- `enabled`: default=False type=<class 'bool'>

- `degree`: default=2 type=<class 'int'>

- `grid`: default=(16, 16) type=tuple[int, int]

- `sigma_clip`: default=3.0 type=<class 'float'>

- `min_samples`: default=None type=typing.Optional[int]
