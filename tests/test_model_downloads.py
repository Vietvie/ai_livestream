import hashlib

from tools import download_musetalk_models, download_wav2lip_model, prepare_avatar


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


def test_ensure_wav2lip_model_downloads_and_verifies(tmp_path, monkeypatch):
    payload = b"official-test-checkpoint"
    destination = tmp_path / "models" / "wav2lip.pth"
    downloads = []

    monkeypatch.setattr(download_wav2lip_model, "EXPECTED_SIZE", len(payload))
    monkeypatch.setattr(
        download_wav2lip_model,
        "EXPECTED_SHA256",
        hashlib.sha256(payload).hexdigest(),
    )

    def fake_download(url, target):
        downloads.append((url, target))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    monkeypatch.setattr(download_wav2lip_model, "_download", fake_download)

    result = download_wav2lip_model.ensure_wav2lip_model(
        destination=destination
    )

    assert result == destination.resolve()
    assert destination.read_bytes() == payload
    assert downloads == [(download_wav2lip_model.MODEL_URL, destination.resolve())]

    # A verified local checkpoint must be reused without another network call.
    download_wav2lip_model.ensure_wav2lip_model(destination=destination)
    assert len(downloads) == 1


def test_ensure_wav2lip_model_replaces_corrupt_existing_file(
    tmp_path, monkeypatch
):
    payload = b"expected-checkpoint"
    destination = tmp_path / "wav2lip.pth"
    destination.write_bytes(b"partial")
    downloads = []

    monkeypatch.setattr(download_wav2lip_model, "EXPECTED_SIZE", len(payload))
    monkeypatch.setattr(
        download_wav2lip_model,
        "EXPECTED_SHA256",
        hashlib.sha256(payload).hexdigest(),
    )

    def fake_download(url, target):
        downloads.append((url, target))
        target.write_bytes(payload)

    monkeypatch.setattr(download_wav2lip_model, "_download", fake_download)

    download_wav2lip_model.ensure_wav2lip_model(destination=destination)

    assert destination.read_bytes() == payload
    assert downloads == [(download_wav2lip_model.MODEL_URL, destination.resolve())]


def test_ensure_wav2lip_avatar_builds_missing_assets(tmp_path, monkeypatch):
    source = tmp_path / "avatar.mp4"
    source.write_bytes(b"video")
    commands = []

    monkeypatch.setattr(prepare_avatar, "ROOT", tmp_path)

    def fake_run(command):
        commands.append(command)
        avatar_dir = tmp_path / "data" / "avatars" / "host01"
        (avatar_dir / "full_imgs").mkdir(parents=True)
        (avatar_dir / "face_imgs").mkdir()
        (avatar_dir / "coords.pkl").write_bytes(b"coords")
        (avatar_dir / "full_imgs" / "00000000.png").write_bytes(b"frame")
        (avatar_dir / "face_imgs" / "00000000.png").write_bytes(b"face")

    monkeypatch.setattr(prepare_avatar, "run", fake_run)

    result = prepare_avatar.ensure_wav2lip_avatar("host01")

    assert result == tmp_path / "data" / "avatars" / "host01"
    assert commands[0][-4:] == ["--avatar-id", "host01", "--model", "wav2lip"]

    prepare_avatar.ensure_wav2lip_avatar("host01")
    assert len(commands) == 1
