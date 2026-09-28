# Cài nhanh GPU Server và OBS Client

Chỉ có 4 bước. Lần chạy đầu các script tự cài thư viện Python, FFmpeg, tải model
cần thiết và chuẩn bị avatar. Những lần sau chỉ khởi động lại dịch vụ.

## 1. Cài các phần mềm cần thiết

### Máy GPU Server Windows

- Cài NVIDIA Studio Driver, sau đó kiểm tra `nvidia-smi` nhận đúng GPU.
- Mở PowerShell Administrator:

```powershell
winget install -e --id Git.Git
winget install -e --id Python.Python.3.12
```

### Máy OBS Client

```powershell
winget install -e --id Python.Python.3.12
winget install -e --id OBSProject.OBSStudio
```

Đóng rồi mở lại PowerShell sau khi cài.

## 2. Clone repo

Trên GPU Server:

```powershell
cd C:\
git clone https://github.com/Vietvie/ai_livestream.git AI_LIVESTREAM
cd C:\AI_LIVESTREAM
```

Copy video mặc định vào:

```text
C:\AI_LIVESTREAM\avatar.mp4
```

Tạo gói nhẹ để gửi cho máy OBS Client:

```powershell
py -3.12 .\tools\build_obs_client_package.py
```

Gửi `dist\AI_LIVESTREAM_OBS_CLIENT.zip` cho người dùng rồi giải nén thành
`C:\AI_LIVESTREAM_CLIENT`.

## 3. Config server và client

### Config server

```powershell
cd C:\AI_LIVESTREAM
Copy-Item .\server-config.example.json .\server-config.json
notepad .\server-config.json
```

Đổi hai khóa bí mật. Server không khai báo trước từng client:

```json
{
  "api_token": "ADMIN_TOKEN_DAI_IT_NHAT_24_KY_TU",
  "client_registration_key": "KHOA_DANG_KY_CLIENT_DAI_IT_NHAT_24_KY_TU",
  "model": "wav2lip",
  "avatar_video": "avatar.mp4",
  "default_avatar_id": "host01",
  "listen_port": 8010,
  "max_clients": 2,
  "batch_size": 4,
  "video_encoder": "h264_nvenc",
  "omnivoice_num_step": 16
}
```

Muốn dùng MuseTalk, chỉ đổi:

```json
"model": "musetalk",
"default_avatar_id": "host01_muse"
```

Mở TCP 8010 nếu client ở máy khác:

```powershell
New-NetFirewallRule -DisplayName "AI Livestream Server" -Direction Inbound -Protocol TCP -LocalPort 8010 -Action Allow
```

### Config client

```powershell
cd C:\AI_LIVESTREAM_CLIENT
Copy-Item .\config.example.json .\config.json
notepad .\config.json
```

```json
{
  "server_url": "http://IP_CUA_GPU_SERVER:8010",
  "client_id": "CLIENT_TU_CHON_ID_RIENG",
  "registration_key": "KHOA_DANG_KY_CLIENT_DAI_IT_NHAT_24_KY_TU",
  "stream_token": "",
  "udp_port": 23000,
  "reconnect_delay": 2.0
}
```

`client_id` do người dùng tự chọn. `registration_key` phải giống server. Trong
lần chạy đầu, client tự đăng ký và lưu `stream_token` riêng vào `config.json`;
khóa đăng ký được xóa khỏi file và các lần sau không đăng ký lại.

Trong OBS tạo **Media Source**:

- Bỏ chọn `Local File`.
- Input: `udp://127.0.0.1:23000`
- Input Format: `mpegts`

## 4. Chạy bằng một lệnh

### Trên GPU Server

```powershell
cd C:\AI_LIVESTREAM
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_server.ps1
```

### Trên OBS Client

```powershell
cd C:\AI_LIVESTREAM_CLIENT
powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

Giữ hai cửa sổ PowerShell hoạt động trong khi livestream. Lần đầu có thể mất
thời gian vì hệ thống tự cài dependency, tải model và chuẩn bị avatar; những lần
sau vẫn dùng đúng hai lệnh trên.

Sau khi hệ thống chạy ổn định, client có thể tự đổi avatar/voice bằng
`create_avatar.ps1` và `create_voice.ps1`; đây là chức năng tùy chọn, không cần
cho lần chạy đầu.
