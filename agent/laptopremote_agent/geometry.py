MIN_WIDTH, MIN_HEIGHT, MAX_SIDE = 320, 200, 4096


def normalize(width, height):
    """Clamp a window size to what the encoder takes and round down to even numbers."""
    width = max(MIN_WIDTH, min(MAX_SIDE, width))
    height = max(MIN_HEIGHT, min(MAX_SIDE, height))
    return width - width % 2, height - height % 2
