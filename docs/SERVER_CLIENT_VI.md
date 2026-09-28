# Mô hình GPU Server – OBS Client đa avatar, đa voice

Hướng dẫn cài nhanh chỉ 4 bước: [QUICKSTART_VI.md](QUICKSTART_VI.md). Tài liệu
này dành cho cấu hình nâng cao và API.

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
- Mỗi client có `stream_token` riêng và chỉ được mở stream của chính nó. Token
  quản trị server không được gửi cho người dùng OBS Client.

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
  -RegistrationKey "KHOA_DANG_KY_CLIENT_DAI_IT_NHAT_24_KY_TU" `
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

## 5. Quản trị client thủ công (tùy chọn)

Thông thường client tự chọn ID và tự đăng ký bằng `registration_key`. Các lệnh
dưới đây chỉ dùng khi quản trị viên muốn tạo/gán profile thủ công.

```powershell
.\.venv\Scripts\python.exe .\tools\broker_admin.py register-client shop-lan `
  --avatar lan `
  --voice voice-lan

.\.venv\Scripts\python.exe .\tools\broker_admin.py register-client shop-minh `
  --avatar minh `
  --voice voice-minh
```

Khi tạo client lần đầu, kết quả trả về có `stream_token`. Hãy lưu token này để
đưa vào `config.json` của đúng OBS Client. Server chỉ lưu hash nên không thể
hiển thị lại token cũ. Nếu làm mất token, tạo token mới:

```powershell
.\.venv\Scripts\python.exe .\tools\broker_admin.py register-client shop-lan `
  --avatar lan `
  --voice voice-lan `
  --rotate-stream-token
```

Token cũ mất hiệu lực ngay sau khi rotate.

Quản trị viên chỉ cần gán avatar mặc định để khởi tạo client. Sau khi nhận
`stream_token`, người dùng có thể tự upload avatar và voice riêng mà không cần
token quản trị:

```powershell
.\.venv\Scripts\python.exe .\tools\broker_admin.py register-client shop-lan `
  --avatar host01
```

Có thể cho hai client dùng chung avatar nhưng voice khác, hoặc dùng chung voice
nhưng avatar khác. Đăng ký lại cùng `client_id` sẽ cập nhật profile và khởi tạo
lại đúng session đó. Hãy dừng OBS Client và chờ job của client hoàn tất trước
khi đổi avatar/voice để không cắt luồng đang phát.

## 6. Clone source OBS Client riêng

Source GPU Server và OBS Client được quản lý bằng hai repo độc lập. Trên máy
OBS Client:

```powershell
cd C:\
git clone https://github.com/Vietvie/ai_livestream_client.git AI_LIVESTREAM_CLIENT
cd C:\AI_LIVESTREAM_CLIENT
```

Repo client: <https://github.com/Vietvie/ai_livestream_client>. Repo này không
chứa server, model, CUDA hoặc token và không cần quyền truy cập source server.

## 7. Cài OBS Client trên máy phát livestream

Máy client chỉ cần Git, Python 3.12 và OBS Studio. Sau khi clone, chạy:

```powershell
cd C:\AI_LIVESTREAM_CLIENT
Copy-Item .\config.example.json .\config.json
notepad .\config.json
```

Nhập địa chỉ server, khóa đăng ký do quản trị cấp và tự chọn ID chưa được dùng:

```json
{
  "server_url": "http://IP_GPU_SERVER:8010",
  "client_id": "shop-lan",
  "registration_key": "KHOA_DANG_KY_CLIENT_DAI_IT_NHAT_24_KY_TU",
  "stream_token": "",
  "udp_port": 23000,
  "reconnect_delay": 2.0
}
```

Khởi động:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Lần đầu, client đăng ký `client_id`, tự ghi token riêng và xóa khóa đăng ký khỏi
`config.json`. Nếu ID đã tồn tại, người dùng phải chọn ID khác.

Để tự setup tài nguyên riêng ngay trong cùng lệnh, đặt `avatar.mp4` và/hoặc
`voice.wav` trong `C:\AI_LIVESTREAM_CLIENT` trước khi chạy `start.ps1`. Có thể
thêm `voice.txt` chứa transcript chính xác. Client chỉ upload khi nội dung file
thay đổi; dùng `start.ps1 -ForceAssets` nếu cần xử lý lại.

### Client tự tạo avatar và voice

Trước tiên dừng `start.ps1`; server không thay tài nguyên khi OBS đang nhận luồng.

Tạo avatar từ video tối đa 500 MB:

```powershell
powershell -ExecutionPolicy Bypass -File .\create_avatar.ps1 `
  -Video .\avatar.mp4
```

Tạo voice clone từ WAV sạch, dài 3–30 giây, tối đa 25 MB:

```powershell
powershell -ExecutionPolicy Bypass -File .\create_voice.ps1 `
  -Audio .\voice.wav
```

Có thể truyền transcript chính xác để bỏ qua ASR:

```powershell
powershell -ExecutionPolicy Bypass -File .\create_voice.ps1 `
  -Audio .\voice.wav `
  -Text "Nội dung chính xác trong file WAV."
```

Hai lệnh dùng `stream_token` trong `config.json`, chờ hàng đợi chuẩn bị xong và
tự gán tài nguyên mới vào profile. Client được tự chọn ID khi đăng ký nhưng
không thể sửa tài nguyên của client khác. Khi hoàn tất, chạy lại `start.ps1`.

Trạng thái tác vụ tài nguyên: `uploading`, `queued`, `waiting_gpu`, `running`,
`completed` hoặc `failed`. Hàng đợi tài nguyên và hàng đợi phát lời dùng chung
khóa GPU, vì vậy chuẩn bị avatar/voice không chạy đồng thời với TTS/lip-sync.

Client tự kết nối lại khi mạng đứt và chỉ copy H.264/AAC, không encode lại.

Trong OBS tạo **Media Source**:

- Bỏ chọn `Local File`.
- Input: `udp://127.0.0.1:23000`
- Input Format: `mpegts`
- Audio Monitoring: `Monitor and Output` nếu cần nghe tại máy OBS.

Mỗi máy OBS có thể dùng port 23000. Nếu chạy nhiều OBS Client trên cùng một
máy, dùng các port 23000, 23002, 23004 và tạo Media Source tương ứng.

## 8. Gửi yêu cầu TTS/lip-sync vào hàng chờ

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

## 9. API chính

Các endpoint quản trị yêu cầu header:

```text
Authorization: Bearer <LIVESTREAM_API_TOKEN>
```

Đây là token quản trị, chỉ dùng cho API quản lý và tạo job. Riêng endpoint
`stream.ts` dùng `stream_token` của client tương ứng.

| Method | Endpoint | Chức năng |
|---|---|---|
| POST | `/api/v1/register` | Client tự chọn ID và đăng ký lần đầu |
| GET | `/api/v1/assets` | Liệt kê avatar và voice |
| PUT | `/api/v1/clients/{client_id}` | Gán avatar/voice cho client |
| GET | `/api/v1/clients` | Liệt kê client profile |
| DELETE | `/api/v1/clients/{client_id}` | Xóa profile/session |
| POST | `/api/v1/voices/{voice_id}` | Upload WAV và transcript tùy chọn |
| POST | `/api/v1/jobs` | Đưa text vào FIFO |
| GET | `/api/v1/jobs/{job_id}` | Xem trạng thái job |
| GET | `/api/v1/queue` | Xem tổng quan hàng chờ |
| GET | `/api/v1/clients/{client_id}/stream.ts` | MPEG-TS riêng của client |
| POST | `/api/v1/clients/{client_id}/assets/avatar` | Client upload video avatar riêng |
| POST | `/api/v1/clients/{client_id}/assets/voice` | Client upload WAV voice riêng |
| GET | `/api/v1/clients/{client_id}/assets/jobs/{job_id}` | Client xem trạng thái chuẩn bị tài nguyên |

Body tạo client:

```json
{"avatar_id": "lan", "voice_id": "voice-lan", "rotate_stream_token": false}
```

Body tạo job:

```json
{"client_id": "shop-lan", "text": "Xin chào mọi người."}
```

## 10. Giới hạn và hướng mở rộng

- FIFO hiện là hàng chờ trong RAM; profile và voice được lưu trên SSD. Khi
  restart server, job nói hoặc job chuẩn bị tài nguyên đang chờ không được phục
  hồi; client cần upload lại nếu tác vụ chưa hoàn tất.
- Một GPU xử lý một job nói tại một thời điểm để tránh quá tải VRAM. Có thể
  scale nhiều GPU bằng cách chạy một server/port trên mỗi GPU và đặt Redis/RQ
  hoặc RabbitMQ ở phía trước.
- HTTP MPEG-TS phù hợp cho mô hình server đẩy về OBS Client qua TCP. Với mạng
  Internet không ổn định, đặt reverse proxy có timeout dài hoặc dùng VPN.
- Không dùng UDP trực tiếp giữa hai máy qua Internet; UDP chỉ dùng loopback từ
  OBS Client tới OBS trên cùng máy.
