from PIL import Image

from wuwa_assistant.vision import image_similarity


def test_identical_frames_match_and_different_frames_do_not():
    black = Image.new("RGB", (20, 20), "black")
    white = Image.new("RGB", (20, 20), "white")
    assert image_similarity(black, black) == 1.0
    assert image_similarity(black, white) == 0.0


def test_similarity_handles_different_sizes():
    a = Image.new("RGB", (20, 20), "#808080")
    b = Image.new("RGB", (10, 10), "#808080")
    assert image_similarity(a, b) == 1.0
