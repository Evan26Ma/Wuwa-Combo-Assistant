import json

from PIL import Image

from wuwa_assistant.vision import (
    StateVisionMonitor,
    TeamVisionMonitor,
    bundled_portrait_paths,
    image_similarity,
    import_okww_portraits,
    import_okww_templates,
    install_bundled_state_templates,
    state_image_similarity,
    template_path,
)


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


def test_import_okww_portraits_selects_largest_square_crop(tmp_path):
    repo = tmp_path / "okww" / "data" / "apps" / "ok-ww" / "repo"
    assets = repo / "assets"
    (assets / "images").mkdir(parents=True)
    Image.new("RGB", (100, 80), "#334455").save(assets / "images" / "one.png")
    annotations = {
        "categories": [{"id": 7, "name": "char_cartethyia"}],
        "images": [{"id": 3, "file_name": "images/one.png", "width": 100, "height": 80}],
        "annotations": [
            {"image_id": 3, "category_id": 7, "bbox": [10, 10, 8, 8]},
            {"image_id": 3, "category_id": 7, "bbox": [30, 20, 30, 20]},
        ],
    }
    (assets / "coco_annotations.json").write_text(json.dumps(annotations), encoding="utf-8")

    imported = import_okww_portraits(tmp_path / "okww", tmp_path / "portraits")

    assert set(imported) == {"卡提希娅"}
    with Image.open(imported["卡提希娅"]) as portrait:
        assert portrait.size == (192, 192)


def test_all_team_portraits_are_bundled():
    portraits = bundled_portrait_paths()
    assert set(portraits) == {"卡提希娅", "夏空", "千咲", "秧秧", "穗穗"}
    for path in portraits.values():
        with Image.open(path) as portrait:
            assert portrait.size == (192, 192)


def test_all_okww_state_templates_are_bundled(tmp_path):
    installed = install_bundled_state_templates(tmp_path / "templates")
    assert len(installed) == 12
    assert "character:夏空" in installed
    assert "cartethyia:lib_big" in installed
    assert "suisui:forte3" in installed
    assert all(template_path(tmp_path / "templates", signal).exists() for signal in installed)


def test_state_roi_scales_to_selected_monitor():
    config = {"roi_ratio": [0.5, 0.25, 0.1, 0.2]}
    monitor = {"left": 100, "top": 50, "width": 2000, "height": 1000}
    assert StateVisionMonitor._roi(config, monitor) == {"left": 1100, "top": 300, "width": 200, "height": 200}


def test_team_vision_selects_unique_best_slot_order():
    team = ("甲", "乙", "丙")
    scores = {
        (0, "甲"): 0.20, (0, "乙"): 0.93, (0, "丙"): 0.31,
        (1, "甲"): 0.22, (1, "乙"): 0.35, (1, "丙"): 0.91,
        (2, "甲"): 0.95, (2, "乙"): 0.18, (2, "丙"): 0.25,
    }
    order, chosen, margin = TeamVisionMonitor.best_order(team, scores)
    assert order == ("乙", "丙", "甲")
    assert chosen == {"slot1": 0.93, "slot2": 0.91, "slot3": 0.95}
    assert margin > 1.0


def test_team_vision_searches_feature_inside_slot_box():
    slot = Image.new("RGB", (80, 90), "black")
    feature = Image.new("RGB", (24, 30), "white")
    slot.paste(feature, (41, 37))
    assert TeamVisionMonitor._best_box_score(slot, feature, feature.size) > 0.95


def test_team_slot_boxes_scale_with_monitor():
    monitor = {"left": 100, "top": 50, "width": 2000, "height": 1000}
    first = TeamVisionMonitor._box_roi(monitor, 0)
    third = TeamVisionMonitor._box_roi(monitor, 2)
    assert first["left"] > 1900
    assert third["top"] > first["top"]
