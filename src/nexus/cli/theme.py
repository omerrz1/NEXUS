"""The CLI color palette and the small color helpers the animations are built from."""

from rich.text import Text

# The blue palette used everywhere in the terminal UI, from light to deep.
SKY = "#70d6ff"
CYAN = "#00b4d8"
BLUE = "#0096c7"
OCEAN = "#0077b6"
INDIGO = "#4361ee"
GLOW = "#caf0f8"
MUTED = "#5c7c8a"
ERROR = "#ff4d6d"
OK = "#3ddc97"
WARN = "#ffb703"

GRADIENT: tuple[str, ...] = (SKY, CYAN, BLUE, OCEAN, INDIGO)

SPINNER_FRAMES: tuple[str, ...] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def blend(start: str, end: str, amount: float) -> str:
    """Return the color `amount` (0 to 1) of the way from `start` to `end`."""
    amount = min(max(amount, 0.0), 1.0)
    start_rgb, end_rgb = _hex_to_rgb(start), _hex_to_rgb(end)
    mixed = (round(s + (e - s) * amount) for s, e in zip(start_rgb, end_rgb, strict=True))
    return "#{:02x}{:02x}{:02x}".format(*mixed)


def gradient_at(position: float) -> str:
    """Return the palette color at `position` (0 to 1) along GRADIENT."""
    scaled = min(max(position, 0.0), 1.0) * (len(GRADIENT) - 1)
    index = min(int(scaled), len(GRADIENT) - 2)
    return blend(GRADIENT[index], GRADIENT[index + 1], scaled - index)


def shimmer(text: str, elapsed: float, base: str = BLUE, highlight: str = GLOW) -> Text:
    """Color `text` with a bright band that sweeps across it as `elapsed` grows."""
    band_width = 4.0
    travel = len(text) + 2 * band_width
    center = (elapsed * 14.0) % travel - band_width
    result = Text()
    for index, char in enumerate(text):
        closeness = 1.0 - abs(index - center) / band_width
        result.append(char, style=f"bold {blend(base, highlight, closeness)}")
    return result


def spinner_frame(elapsed: float) -> str:
    """Return the spinner glyph for this moment."""
    return SPINNER_FRAMES[int(elapsed * 12) % len(SPINNER_FRAMES)]
