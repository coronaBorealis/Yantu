from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from yantu.main import create_app
from yantu.services.appearance_service import AppearanceService


PNG = b"\x89PNG\r\n\x1a\n" + b"test-background"


def test_default_save_and_corrupt_config_fallback(tmp_path: Path) -> None:
    service = AppearanceService(tmp_path / "appearance.json", tmp_path / "appearance")
    assert service.get()["preset"] == "forest"
    saved = service.save({
        "preset": "night", "mode": "dark", "surface_opacity": 0.9,
        "background": {
            "type": "gradient", "color": "#123456",
            "gradient_start": "#102030", "gradient_end": "#405060",
            "gradient_angle": 45,
        },
    })
    assert saved["background"]["gradient_angle"] == 45
    assert not list(tmp_path.glob("appearance-*.tmp"))
    (tmp_path / "appearance.json").write_text("{broken", encoding="utf-8")
    assert service.get()["preset"] == "forest"


@pytest.mark.parametrize("field,value", [
    ("preset", "unknown"),
    ("mode", "sepia"),
    ("surface_opacity", 0.5),
])
def test_invalid_settings_are_rejected(tmp_path: Path, field: str, value: object) -> None:
    service = AppearanceService(tmp_path / "appearance.json", tmp_path / "appearance")
    payload = service.get()
    payload[field] = value
    with pytest.raises(ValueError):
        service.save(payload)


def test_appearance_api_image_and_backup_round_trip(tmp_path: Path) -> None:
    source = create_app(tmp_path / "source.db").test_client()
    assert source.get("/api/appearance").get_json()["appearance"]["mode"] == "system"
    updated = source.put("/api/appearance", json={
        "preset": "paper", "mode": "light", "surface_opacity": 0.94,
        "background": {
            "type": "solid", "color": "#fffaf0",
            "gradient_start": "#ffffff", "gradient_end": "#eeeeee",
            "gradient_angle": 90,
        },
    })
    assert updated.status_code == 200
    uploaded = source.post(
        "/api/appearance/background",
        data={"file": (io.BytesIO(PNG), "study.png")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 201
    assert source.get("/api/appearance/background").data == PNG
    backup = source.get("/api/export").get_json()
    assert backup["appearance"]["background"]["data_base64"]

    target = create_app(tmp_path / "target.db").test_client()
    restored = target.post("/api/import", json=backup)
    assert restored.status_code == 200
    assert restored.get_json()["appearance_imported"] is True
    assert target.get("/api/appearance/background").data == PNG
    removed = target.delete("/api/appearance/background")
    assert removed.status_code == 200
    assert target.get("/api/appearance/background").status_code == 404


def test_background_validation(tmp_path: Path) -> None:
    client = create_app(tmp_path / "invalid.db").test_client()
    mismatch = client.post(
        "/api/appearance/background",
        data={"file": (io.BytesIO(PNG), "study.jpg")},
        content_type="multipart/form-data",
    )
    assert mismatch.status_code == 400
    bad_color = client.put("/api/appearance", json={
        "preset": "forest", "mode": "system", "surface_opacity": 0.92,
        "background": {"type": "solid", "color": "red"},
    })
    assert bad_color.status_code == 400
    service = AppearanceService(tmp_path / "appearance.json", tmp_path / "appearance")
    with pytest.raises(ValueError, match="8 MB"):
        service.save_background("large.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"x" * (8 * 1024 * 1024))


def test_logo_assets_and_shortcut_are_valid(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    assets = root / "src" / "yantu" / "web" / "assets"
    for size in (512, 192, 64, 32, 16):
        with Image.open(assets / f"logo-{size}.png") as icon:
            assert icon.size == (size, size)
            assert icon.mode == "RGBA"
    with Image.open(assets / "yantu.ico") as icon:
        assert icon.format == "ICO"
        assert {(16, 16), (32, 32), (64, 64)} <= set(icon.info["sizes"])

    destination = tmp_path / "中文桌面"
    command = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(root / "scripts" / "install-shortcut.ps1"),
        "-DestinationDirectory", str(destination), "-PassThru",
    ]
    for _ in range(2):
        result = subprocess.run(
            command, check=True, capture_output=True, text=True, encoding="utf-8"
        )
        details = json.loads(result.stdout)
        assert details["TargetPath"].endswith("start.bat")
        assert details["WorkingDirectory"] == str(root)
        assert details["IconLocation"].endswith("yantu.ico,0")
    assert (destination / "Yantu 研途.lnk").is_file()
