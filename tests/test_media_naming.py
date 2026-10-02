from datetime import datetime
from pathlib import Path

from renameimg.media import scan
from renameimg.naming import NameAllocator, already_named, base_stem


def touch(root: Path, *names: str) -> None:
    for name in names:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")


def test_scan_groups_live_photo_and_sidecars(tmp_path):
    touch(tmp_path, "IMG_1.HEIC", "IMG_1.MOV", "IMG_1.AAE", "IMG_1.HEIC.xmp")
    result = scan(tmp_path)
    assert len(result.groups) == 1
    g = result.groups[0]
    assert g.kind == "image"
    assert g.primary.path.name == "IMG_1.HEIC"
    by_name = {m.path.name: m for m in g.members}
    assert by_name["IMG_1.MOV"].live
    assert by_name["IMG_1.HEIC.xmp"].suffix == ".HEIC.xmp"
    assert by_name["IMG_1.AAE"].suffix == ".AAE"


def test_scan_prefers_image_over_raw_as_primary(tmp_path):
    touch(tmp_path, "DSC_1.NEF", "DSC_1.JPG")
    g = scan(tmp_path).groups[0]
    assert g.primary.path.name == "DSC_1.JPG"
    assert len(g.members) == 2


def test_scan_splits_videos_and_reports_unknown(tmp_path):
    touch(tmp_path, "a.mov", "a.mp4", "notes.txt", "orphan.xmp")
    result = scan(tmp_path)
    assert [g.kind for g in result.groups] == ["video", "video"]
    assert sorted(p.name for p in result.unknown) == ["notes.txt", "orphan.xmp"]


def test_scan_skips_hidden_and_nas_dirs_and_finds_stale_tmp(tmp_path):
    touch(
        tmp_path,
        ".DS_Store",
        "._IMG_1.JPG",
        "@eaDir/IMG_1.JPG/SYNOFILE_THUMB_M.jpg",
        "#recycle/old.jpg",
        ".renameimg-tmp-VID_1.mp4",
        "sub/IMG_2.JPG",
    )
    result = scan(tmp_path)
    assert [g.primary.path.name for g in result.groups] == ["IMG_2.JPG"]
    assert [p.name for p in result.stale_tmp] == [".renameimg-tmp-VID_1.mp4"]


def test_already_named():
    base = base_stem("IMG_", datetime(2023, 10, 5, 14, 22, 33))
    assert base == "IMG_20231005_142233"
    assert already_named("IMG_20231005_142233", base)
    assert already_named("IMG_20231005_142233_2", base)
    assert not already_named("IMG_20231005_142233_x", base)
    assert not already_named("IMG_1234", base)


def test_allocator_avoids_existing_files_and_reservations(tmp_path):
    touch(tmp_path, "IMG_X.jpg", "a.jpg", "b.jpg", "c.jpg")
    alloc = NameAllocator()
    # 既有的別的檔案 → _1
    assert alloc.allocate("IMG_X", tmp_path, [(tmp_path / "a.jpg", ".jpg")]) == "IMG_X_1"
    # 本次已分配 → _2
    assert alloc.allocate("IMG_X", tmp_path, [(tmp_path / "b.jpg", ".jpg")]) == "IMG_X_2"
    # 不同副檔名不衝突
    assert alloc.allocate("IMG_X", tmp_path, [(tmp_path / "c.jpg", ".heic")]) == "IMG_X"


def test_allocator_checks_every_member(tmp_path):
    touch(tmp_path, "IMG_X.mov", "a.heic", "a.mov")
    alloc = NameAllocator()
    members = [(tmp_path / "a.heic", ".heic"), (tmp_path / "a.mov", ".mov")]
    assert alloc.allocate("IMG_X", tmp_path, members) == "IMG_X_1"


def test_allocator_treats_own_file_as_free(tmp_path):
    touch(tmp_path, "IMG_X.JPG")
    alloc = NameAllocator()
    # 只改副檔名大小寫：在不分大小寫的檔案系統上目標就是自己
    assert alloc.allocate("IMG_X", tmp_path, [(tmp_path / "IMG_X.JPG", ".jpg")]) == "IMG_X"
