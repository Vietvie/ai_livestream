# AI Livestream OBS Client

Đây là client độc lập dành cho máy chạy OBS. Client chỉ nhận luồng H.264/AAC
từ GPU Server và chuyển tiếp tới OBS qua UDP loopback; không chứa model AI,
avatar, voice, CUDA hay source server.

Phần mềm được phân phối theo giấy phép Apache 2.0 trong file `LICENSE`.

## Cài đặt trên Windows

Yêu cầu: Python 3.12 và OBS Studio.

Mở PowerShell trong thư mục này:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
notepad .\config.json
```

Sửa ba giá trị do quản trị server cấp:

```json
{
  "server_url": "http://IP_GPU_SERVER:8010",
  "client_id": "shop-lan",
  "stream_token": "TOKEN_RIENG_DO_SERVER_CAP_CHO_CLIENT_NAY",
  "udp_port": 23000,
  "reconnect_delay": 2.0
}
```

Chạy client:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

## Cấu hình OBS

Tạo **Media Source**:

- Bỏ chọn `Local File`.
- Input: `udp://127.0.0.1:23000`
- Input Format: `mpegts`
- Chọn `Monitor and Output` nếu muốn nghe âm thanh tại máy OBS.

Client tự kết nối lại khi mạng bị gián đoạn. Giữ cửa sổ PowerShell hoạt động
trong suốt phiên livestream; nhấn `Ctrl+C` để dừng.

`stream_token` chỉ truy cập được stream của đúng `client_id`, không có quyền
quản trị server. Dù vậy, không chia sẻ `config.json` cho người khác.
