import json

from PIL import Image

from wuwa_assistant.vision import StateVisionMonitor, image_similarity, import_okww_templates, state_image_similarity, template_path


def test_identical_frames_match_and_different_frames_do_not():
    black = Image.new("RGB", (20, 20), "black")
    white = Image.new("RGB", (20, 20), "white")
    assert image_similarity(black, black) == 1.0
    assert image_similarity(black, white) == 0.0


def test_similarity_handles_different_sizes():
    a = Image.new("RGB", (20, 20), "#808080")
    b = Image.new("RGB", (10, 10), "#808080")
    assert image_similarity(a, b) == 1.0


def test_state_similarity_combines_color_and_edges():
    black = Image.new("RGB", (20, 20), "black")
    white = Image.new("RGB", (20, 20), "white")
    assert state_image_similarity(black, black) == 1.0
    assert state_image_similarity(black, white) < 0.35


def test_imports_supported_template_from_local_okww_coco(tmp_path):
    repo = tmp_path / "okww" / "repo"
    assets = repo / "assets"
    images = assets / "images"
    images.mkdir(parents=True)
    Image.new("RGB", (100, 100), "white").save(images / "0.png")
    coco = {
        "categories": [{"id": 1, "name": "forte_cartethyia_sword1"}],
        "images": [{"id": 1, "file_name": "images/0.png", "width": 100, "height": 100}],
        "annotations": [{"id": 1, "category_id": 1, "image_id": 1, "bbox": [10, 20, 30, 40]}],
    }
    (assets / "coco_annotations.json").write_text(json.dumps(coco), encoding="utf-8")
    templates = tmp_path / "templates"
    imported = import_okww_templates(tmp_path / "okww", templates)
    assert imported["cartethyia:sword1"]["roi_ratio"] == [0.1, 0.2, 0.3, 0.4]
    with Image.open(template_path(templates, "cartethyia:sword1")) as crop:
        assert crop.size == (30, 40)


def test_state_roi_scales_to_selected_monitor():
    config = {"roi_ratio": [0.5, 0.25, 0.1, 0.2]}
    monitor = {"left": 100, "top": 50, "width": 2000, "height": 1000}
    assert StateVisionMonitor._roi(config, monitor) == {"left": 1100, "top": 300, "width": 200, "height": 200}
