# Mô hình GPU Server – OBS Client đa avatar, đa voice

## 1. Kiến trúc

```text
Ứng dụng/API gửi text
          |
          v
GPU Server: HTTP API -> FIFO toàn cục -> OmniVoice -> Wav2Lip/MuseTalk
          |                              |
          |                    avatar + voice theo client_id
          v
HTTP MPEG-TS riêng: /api/v1/clients/<client_id>/stream.ts
          |
          v
OBS Client: FFmpeg copy stream -> udp://127.0.0.1:23000 -> OBS Media Source
```

- Mỗi `client_id` lưu một `avatar_id` và một `voice_id` riêng.
- Profile được lưu tại `data/broker/clients.json` trên server.
- Voice được lưu tại `data/voices/broker/` trên server.
- Avatar dùng lại kho `data/avatars/<avatar_id>` hiện có.
- Tất cả job nói đi qua một hàng chờ FIFO toàn cục. Một GPU chỉ xử lý một câu
  tại một thời điểm; các client khác vẫn nhận hình avatar im lặng.
- OBS Client phải kết nối trước khi gửi job. Server chờ tối đa 30 giây; nếu
  client chưa nhận stream, job chuyển `failed` thay vì tạo audio rồi làm mất nó.
- Model OmniVoice lớn được dùng chung giữa các session. Voice prompt vẫn tách
  biệt theo client, tránh nạp nhiều bản model vào VRAM.
- Mỗi stream dùng NVENC mặc định để tránh CPU tăng cao khi có nhiều client.
- Mỗi client có một luồng MPEG-TS riêng nên không thể nhận nhầm hình hoặc tiếng
  của client khác.

Một tiến trình server chỉ chạy một loại backend avatar. Nếu cần đồng thời
Wav2Lip và MuseTalk, chạy hai server ở hai GPU hoặc hai port khác nhau.

## 2. Khởi động GPU Server Windows

Sau khi cài source theo hướng dẫn VPS hiện có:

```powershell
cd C:\AI_LIVESTREAM
git pull origin main
$env:LIVESTREAM_API_TOKEN="THAY_BANG_TOKEN_DAI_NGAU_NHIEN"

powershell -ExecutionPolicy Bypass -File .\scripts\run_queue_server_windows.ps1 `
  -Model way2lip `
  -DefaultAvatarId host01 `
  -MaxClients 4 `
  -BatchSize 4 `
  -ListenPort 8010
```

Server lắng nghe `0.0.0.0:8010`. Với RTX 5060 Ti 16 GB, nên thử 2 client trước,
sau đó tăng dần tới 4. `MaxClients` là số stream/session tồn tại đồng thời;
hàng chờ vẫn xử lý câu nói tuần tự.

Cho phép inbound TCP 8010 trên Windows Firewall nếu OBS Client nằm ở máy khác.
Khi chạy qua Internet, nên đặt API sau HTTPS reverse proxy hoặc VPN; không gửi
Bearer token qua HTTP công khai.

## 3. Chuẩn bị nhiều avatar

Mỗi avatar có một ID riêng. Ví dụ:

```powershell
cd C:\AI_LIVESTREAM
$env:PATH="$PWD\bin;$env:PATH"

.\.venv\Scripts\python.exe .\tools\prepare_avatar.py .\avatar-lan.mp4 `
  --avatar-id lan `
  --model wav2lip

.\.venv\Scripts\python.exe .\tools\prepare_avatar.py .\avatar-minh.mp4 `
  --avatar-id minh `
  --model wav2lip
```

Kiểm tra tài nguyên server:

```powershell
.\.venv\Scripts\python.exe .\tools\broker_admin.py assets
```

## 4. Lưu nhiều voice

Chỉ sử dụng mẫu giọng khi có sự đồng ý của người sở hữu. Mỗi WAV nên sạch,
một người nói, dài 3–30 giây và không có nhạc nền.

Không cần tự nhập transcript; server tự chuẩn hóa và chép lời tiếng Việt:

```powershell
.\.venv\Scripts\python.exe .\tools\broker_admin.py upload-voice voice-lan `
  --file C:\AI_LIVESTREAM\voices\lan.wav

.\.venv\Scripts\python.exe .\tools\broker_admin.py upload-voice voice-minh `
  --file C:\AI_LIVESTREAM\voices\minh.wav
```

Lần đầu server tải PhoWhisper-medium. Nếu đã có transcript chính xác, truyền
thêm `--text "Nội dung chính xác trong file WAV."` để bỏ qua ASR.

## 5. Gán avatar và voice cho từng client

```powershell
.\.venv\Scripts\python.exe .\tools\broker_admin.py register-client shop-lan `
  --avatar lan `
  --voice voice-lan

.\.venv\Scripts\python.exe .\tools\broker_admin.py register-client shop-minh `
  --avatar minh `
  --voice voice-minh
```

Có thể cho hai client dùng chung avatar nhưng voice khác, hoặc dùng chung voice
nhưng avatar khác. Đăng ký lại cùng `client_id` sẽ cập nhật profile và khởi tạo
lại đúng session đó. Hãy dừng OBS Client và chờ job của client hoàn tất trước
khi đổi avatar/voice để không cắt luồng đang phát.

## 6. Cài OBS Client trên máy phát livestream

Máy client không cần CUDA, model AI hoặc GPU inference. Clone/pull repo rồi chạy:

```powershell
cd C:\AI_LIVESTREAM
powershell -ExecutionPolicy Bypass -File .\scripts\setup_obs_client_windows.ps1
$env:LIVESTREAM_API_TOKEN="THAY_BANG_TOKEN_GIONG_SERVER"

powershell -ExecutionPolicy Bypass -File .\scripts\run_obs_client_windows.ps1 `
  -ServerUrl "http://IP_GPU_SERVER:8010" `
  -ClientId "shop-lan" `
  -UdpPort 23000
```

Client tự kết nối lại khi mạng đứt và chỉ copy H.264/AAC, không encode lại.

Trong OBS tạo **Media Source**:

- Bỏ chọn `Local File`.
- Input: `udp://127.0.0.1:23000`
- Input Format: `mpegts`
- Audio Monitoring: `Monitor and Output` nếu cần nghe tại máy OBS.

Mỗi máy OBS có thể dùng port 23000. Nếu chạy nhiều OBS Client trên cùng một
máy, dùng các port 23000, 23002, 23004 và tạo Media Source tương ứng.

## 7. Gửi yêu cầu TTS/lip-sync vào hàng chờ

Từ server hoặc bất kỳ máy nào có `broker_admin.py`:

```powershell
.\.venv\Scripts\python.exe .\tools\broker_admin.py `
  --server "http://IP_GPU_SERVER:8010" `
  speak shop-lan "Xin chào, sản phẩm hôm nay đang có ưu đãi rất tốt."

.\.venv\Scripts\python.exe .\tools\broker_admin.py `
  --server "http://IP_GPU_SERVER:8010" `
  speak shop-minh "Mình sẽ tư vấn sản phẩm phù hợp với nhu cầu của bạn."
```

Response trả về `job_id`. Kiểm tra job và hàng chờ:

```powershell
.\.venv\Scripts\python.exe .\tools\broker_admin.py job JOB_ID
.\.venv\Scripts\python.exe .\tools\broker_admin.py status
```

Trạng thái job: `queued`, `waiting_client`, `running`, `completed` hoặc `failed`.

## 8. API chính

Tất cả endpoint yêu cầu header:

```text
Authorization: Bearer <LIVESTREAM_API_TOKEN>
```

| Method | Endpoint | Chức năng |
|---|---|---|
| GET | `/api/v1/assets` | Liệt kê avatar và voice |
| PUT | `/api/v1/clients/{client_id}` | Gán avatar/voice cho client |
| GET | `/api/v1/clients` | Liệt kê client profile |
| DELETE | `/api/v1/clients/{client_id}` | Xóa profile/session |
| POST | `/api/v1/voices/{voice_id}` | Upload WAV và transcript tùy chọn |
| POST | `/api/v1/jobs` | Đưa text vào FIFO |
| GET | `/api/v1/jobs/{job_id}` | Xem trạng thái job |
| GET | `/api/v1/queue` | Xem tổng quan hàng chờ |
| GET | `/api/v1/clients/{client_id}/stream.ts` | MPEG-TS riêng của client |

Body tạo client:

```json
{"avatar_id": "lan", "voice_id": "voice-lan"}
```

Body tạo job:

```json
{"client_id": "shop-lan", "text": "Xin chào mọi người."}
```

## 9. Giới hạn và hướng mở rộng

- FIFO hiện là hàng chờ trong RAM; profile và voice được lưu trên SSD. Khi
  restart server, job đang chờ không được phục hồi.
- Một GPU xử lý một job nói tại một thời điểm để tránh quá tải VRAM. Có thể
  scale nhiều GPU bằng cách chạy một server/port trên mỗi GPU và đặt Redis/RQ
  hoặc RabbitMQ ở phía trước.
- HTTP MPEG-TS phù hợp cho mô hình server đẩy về OBS Client qua TCP. Với mạng
  Internet không ổn định, đặt reverse proxy có timeout dài hoặc dùng VPN.
- Không dùng UDP trực tiếp giữa hai máy qua Internet; UDP chỉ dùng loopback từ
  OBS Client tới OBS trên cùng máy.
