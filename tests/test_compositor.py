import cv2
import numpy as np
import pytest

from backend.editing.compositor import Compositor
from backend.editing.config import EditConfig, Region
from backend.editing.reframe import CameraPath, zoom_envelope

W, H = 1920, 1080
CAM = Region(x=0.03, y=0.65, w=0.21, h=0.29)


def frame_with_circle() -> np.ndarray:
    f = np.full((H, W, 3), 40, np.uint8)
    cv2.circle(f, (W // 2, H // 2), 200, (255, 255, 255), -1)
    x0, y0 = int(CAM.x * W), int(CAM.y * H)
    f[y0:y0 + int(CAM.h * H), x0:x0 + int(CAM.w * W)] = (0, 0, 255)  # webcam = pure red
    return f


def blob_aspect(img: np.ndarray) -> float:
    mask = (img.min(axis=2) > 200).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    big = stats[1:][np.argmax(stats[1:, cv2.CC_STAT_AREA])]
    return big[cv2.CC_STAT_WIDTH] / big[cv2.CC_STAT_HEIGHT]


@pytest.mark.parametrize("layout,crop", [("full", "smart"), ("full", "fit"), ("stack", "center"),
                                         ("pip", "center"), ("split", "center")])
def test_layouts_output_size_and_no_distortion(layout, crop):
    comp = Compositor(EditConfig(layout=layout, crop_mode=crop, zoom=False), W, H, webcam=CAM,
                      path=CameraPath.fixed(), zoom_fn=lambda t: 0.0)
    out = comp.compose(frame_with_circle(), 0.0)
    assert out.shape == (1920, 1080, 3)
    assert blob_aspect(out) == pytest.approx(1.0, abs=0.06), "the circle must stay a circle"


def test_webcam_shown_in_its_box_and_hidden_from_gameplay():
    comp = Compositor(EditConfig(layout="stack", crop_mode="smart", zoom=False), W, H, webcam=CAM,
                      path=CameraPath.fixed(0.05), zoom_fn=lambda t: 0.0)  # camera pushed towards the webcam
    out = comp.compose(frame_with_circle(), 0.0)
    g = comp.gameplay_box(0)
    red = (out[..., 2] > 200) & (out[..., 1] < 50) & (out[..., 0] < 50)
    assert red[g.h + 10:].mean() > 0.9           # webcam fills the bottom area
    assert red[: g.h - 10].mean() < 0.01         # and is kept out of the gameplay crop


def test_zoom_envelope_and_dynamic_split():
    assert zoom_envelope(5.0, [5.0]) == 1.0 and zoom_envelope(0.0, [5.0]) == 0.0
    assert 0 < zoom_envelope(4.9, [5.0]) < 1
    comp = Compositor(EditConfig(layout="split"), W, H, webcam=CAM, path=CameraPath.fixed(),
                      zoom_fn=lambda t: zoom_envelope(t, [5.0]))
    assert comp.gameplay_box(5.0).h > comp.gameplay_box(0.0).h  # gameplay grows on the action peak
