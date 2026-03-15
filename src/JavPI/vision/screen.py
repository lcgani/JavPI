import numpy as np
import mss


class ScreenCapture:

    def capture_full(self):
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            screenshot = sct.grab(monitor)
            img = np.array(screenshot)
            return img[:, :, :3][:, :, ::-1]

    def capture_region(self, x, y, width, height):
        with mss.mss() as sct:
            region = {'left': x, 'top': y, 'width': width, 'height': height}
            screenshot = sct.grab(region)
            img = np.array(screenshot)
            return img[:, :, :3][:, :, ::-1]