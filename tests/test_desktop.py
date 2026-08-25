from __future__ import annotations

from pathlib import Path

from yantu.desktop import APP_MUTEX_NAME, smoke_test


def test_desktop_smoke_uses_isolated_data_and_embeds_request_token(tmp_path: Path) -> None:
    data_dir = tmp_path / "中文安装数据"
    assert smoke_test(data_dir) == 0
    assert (data_dir / "yantu.db").is_file()
    assert not (data_dir / "runtime.json").exists()


def test_installer_is_current_user_and_preserves_user_data() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "packaging" / "yantu.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in script
    assert "DefaultDirName={localappdata}\\Programs\\Yantu" in script
    assert f"AppMutex={APP_MUTEX_NAME}" in script
    assert "[UninstallDelete]" not in script
    assert "Yantu.exe" in script
