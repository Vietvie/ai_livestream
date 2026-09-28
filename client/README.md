# AI Livestream OBS Client

Đây là client độc lập dành cho máy chạy OBS. Client chỉ nhận luồng H.264/AAC
từ GPU Server và chuyển tiếp tới OBS qua UDP loopback; không chứa model AI,
avatar, voice, CUDA hay source server.

Phần mềm được phân phối theo giấy phép Apache 2.0 trong file `LICENSE`.

## Cài đặt trên Windows

Yêu cầu: Python 3.12 và OBS Studio.

Tạo config trong thư mục này:

```powershell
Copy-Item .\config.example.json .\config.json
notepad .\config.json
```

Nhập địa chỉ server, khóa đăng ký do quản trị cấp và tự chọn `client_id`:

```json
{
  "server_url": "http://IP_GPU_SERVER:8010",
  "client_id": "ID_TU_CHON_KHONG_TRUNG_CLIENT_KHAC",
  "registration_key": "KHOA_DANG_KY_DO_SERVER_CAP",
  "stream_token": "",
  "udp_port": 23000,
  "reconnect_delay": 2.0
}
```

Chạy client bằng một lệnh. Lần đầu script tự cài môi trường nhẹ và FFmpeg:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

Lần chạy đầu client tự đăng ký ID, ghi token riêng và xóa khóa đăng ký khỏi
`config.json`. Nếu ID đã có người sử dụng, hãy đổi `client_id` rồi chạy lại.

## Tự tạo avatar riêng

Dừng `start.ps1` trước khi đổi avatar hoặc voice. Chỉ dùng hình ảnh của bạn hoặc
người đã đồng ý. Video nên có một khuôn mặt rõ, góc quay chính diện, ánh sáng
ổn định; dung lượng tối đa 500 MB:

```powershell
powershell -ExecutionPolicy Bypass -File .\create_avatar.ps1 `
  -Video .\avatar.mp4
```

Client upload video, server tự chuẩn hóa và tạo avatar theo backend đang chạy.
Lệnh chờ đến khi hoàn tất rồi tự gán avatar mới vào đúng `client_id`.

## Tự tạo voice clone riêng

Chỉ dùng giọng nói khi bạn là chủ sở hữu hoặc đã có sự đồng ý. WAV cần sạch,
một người nói, dài 3–30 giây và tối đa 25 MB:

```powershell
powershell -ExecutionPolicy Bypass -File .\create_voice.ps1 `
  -Audio .\voice.wav
```

Server tự chép lời tiếng Việt. Nếu đã biết transcript chính xác:

```powershell
powershell -ExecutionPolicy Bypass -File .\create_voice.ps1 `
  -Audio .\voice.wav `
  -Text "Nội dung chính xác được nói trong file."
```

Sau khi avatar/voice báo `completed`, chạy lại `start.ps1`. Nếu dùng `--no-wait`,
kiểm tra sau bằng:

```powershell
.\.venv\Scripts\python.exe .\manage_assets.py status JOB_ID
```

## Cấu hình OBS

Tạo **Media Source**:

- Bỏ chọn `Local File`.
- Input: `udp://127.0.0.1:23000`
- Input Format: `mpegts`
- Chọn `Monitor and Output` nếu muốn nghe âm thanh tại máy OBS.

Client tự kết nối lại khi mạng bị gián đoạn. Giữ cửa sổ PowerShell hoạt động
trong suốt phiên livestream; nhấn `Ctrl+C` để dừng.

`registration_key` chỉ dùng trong lần đăng ký đầu. `stream_token` chỉ truy cập
stream và quản lý avatar/voice của đúng `client_id`,
không có quyền quản trị server hoặc tài nguyên client khác. Dù vậy, không chia
sẻ `config.json` cho người khác.
