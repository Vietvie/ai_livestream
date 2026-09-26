from tools import download_musetalk_models


def test_ensure_musetalk_models_downloads_only_missing_files(tmp_path, monkeypatch):
    present_dir = tmp_path / "present"
    missing_dir = tmp_path / "missing"
    present_dir.mkdir()
    (present_dir / "present.bin").write_bytes(b"ready")

    downloads = [
        ("example/present", "present.bin", present_dir),
        ("example/missing", "nested/missing.bin", missing_dir),
    ]
    requested = []

    def fake_hf_file(repo_id, filename, destination):
        requested.append((repo_id, filename, destination))
        target = destination / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"downloaded")

    monkeypatch.setattr(download_musetalk_models, "DOWNLOADS", downloads)
    monkeypatch.setattr(download_musetalk_models, "hf_file", fake_hf_file)

    download_musetalk_models.ensure_musetalk_models()

    assert requested == [("example/missing", "nested/missing.bin", missing_dir)]
    assert (missing_dir / "nested" / "missing.bin").read_bytes() == b"downloaded"
