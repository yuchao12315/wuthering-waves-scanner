import mss
import numpy as np
from PIL import Image

_sct = mss.mss()


def capture_region(x, y, w, h):
    """Capture a screen region, returns PIL Image."""
    monitor = {'left': x, 'top': y, 'width': w, 'height': h}
    img = _sct.grab(monitor)
    return Image.frombytes('RGB', img.size, img.bgra, 'raw', 'BGRX')


def capture_game_region(game_rect, region):
    """Capture a region relative to game window."""
    gx, gy, gw, gh = game_rect
    rx, ry, rw, rh = region
    return capture_region(gx + rx, gy + ry, rw, rh)


def images_similar(img1, img2, threshold=0.95):
    """Check if two images are similar (for scroll detection)."""
    arr1 = np.array(img1.resize((200, 150)))
    arr2 = np.array(img2.resize((200, 150)))
    diff = np.abs(arr1.astype(float) - arr2.astype(float))
    similarity = 1.0 - (diff.mean() / 255.0)
    return similarity > threshold
