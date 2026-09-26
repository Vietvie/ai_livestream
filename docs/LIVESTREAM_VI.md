# Bộ công cụ AI livestream realtime (không giao diện)

Đây là lớp điều phối bổ sung trên LiveTalking. Luồng chạy chính:

```text
Comment/API -> hàng đợi ưu tiên -> OpenAI Responses API -> TTS
            -> Wav2Lip/MuseTalk -> RTMP hoặc virtual camera -> OBS

Không có comment -> bộ kịch bản -> TTS/clip hành động -> avatar -> OBS
```

## 1. Chức năng đã có

- Nhận bình luận qua HTTP API, chống xử lý trùng bằng `comment_id`.
- Trả lời tư vấn bằng OpenAI, có lịch sử hội thoại riêng theo `sessionid`.
- Chỉ đưa các sản phẩm liên quan từ catalog vào prompt để giảm trả lời sai giá,
  khuyến mãi và tồn kho.
- Stream từng cụm câu sang TTS, không phải chờ toàn bộ câu trả lời.
- Khi im lặng quá thời gian cấu hình, tự phát lần lượt các kịch bản trong
  `data/scripts.yaml`.
- Kịch bản có thể là lời cố định (`mode: direct`) hoặc prompt tạo lời mới
  (`mode: generate`). Có thể gắn `audiotype` để phát clip hành động đã chuẩn bị.
- Xử lý video người dẫn quay sẵn thành avatar Wav2Lip/MuseTalk.
- Xuất WebRTC, RTMP hoặc virtual camera; có thể ghi MP4 bằng API gốc LiveTalking.
- API điều khiển có Bearer token, phù hợp để bộ đọc comment TikTok/Facebook/
  YouTube ở tiến trình khác gọi vào.

## 2. Chuẩn bị dữ liệu

### Chế độ dummy và API key

Mặc định `openai.provider: dummy`, hệ thống tạo lời mẫu cục bộ và **không cần
OpenAI API key**. Chế độ này dùng để ưu tiên kiểm tra TTS, lip-sync, ghi MP4 và
đường truyền OBS. Khi muốn bật LLM thật, đổi `provider: openai` rồi điền key.
TTS mặc định là EdgeTTS với giọng nữ tiếng Việt `vi-VN-HoaiMyNeural`.
Nếu VPS/datacenter bị Microsoft Edge TTS chặn, dùng `--tts sapi --REF_FILE ""`
để kiểm thử hoàn toàn offline bằng giọng Windows đang cài trên VPS.

Sao chép `.env.example` thành `.env`, sau đó điền:

```dotenv
OPENAI_API_KEY=sk-... # bỏ trống khi provider=dummy
LIVESTREAM_API_TOKEN=mot-chuoi-dai-ngau-nhien
```

Không commit `.env`. Mô hình, prompt và tên biến key nằm trong
`config/livestream.yaml`.

### Catalog sản phẩm

Thay dữ liệu mẫu trong `data/products.json`. Nên giữ các trường rõ nghĩa như:

```json
{
  "sku": "SKU-001",
  "name": "Tên thật",
  "price_vnd": 499000,
  "promotion": "Nội dung và thời hạn",
  "stock_status": "in_stock",
  "features": ["..."],
  "suitable_for": ["..."],
  "warranty": "...",
  "faq": [{"question": "...", "answer": "..."}]
}
```

### Kịch bản lúc không có comment

Sửa `data/scripts.yaml`. `idle_seconds` trong `config/livestream.yaml` quyết định
thời gian chờ. Ví dụ tạo lời động:

```yaml
- id: highlight-a
  mode: generate
  text: "Giới thiệu SKU-001 trong 3 câu, đúng dữ liệu catalog và không thêm ưu đãi."
```

Nếu đã chuẩn bị clip hành động theo `data/custom_config.json`, thêm
`audiotype: 2`. Clip sẽ phát trước; lời TTS tiếp tục sau clip.

## 3. Biến video quay sẵn thành avatar

Video nên nhìn thẳng, mặt không bị che, ánh sáng ổn định, đầu/khung hình ít rung.
Lệnh dưới đây chuẩn hóa 25 fps, kích thước 720x1280 rồi tạo dữ liệu avatar:

```bash
python tools/prepare_avatar.py presenter.mp4 \
  --avatar-id host01 \
  --model wav2lip
```

Hoặc gửi video từ xa qua API có sẵn:

```bash
curl -X POST http://SERVER:8010/api/avatar/task \
  -H "Authorization: Bearer $LIVESTREAM_API_TOKEN" \
  -F model=wav2lip \
  -F avatar_id=host01 \
  -F video_file=@presenter.mp4
```

Theo dõi bằng `GET /api/avatar/task/{task_id}`. Cách CLI có thêm bước chuẩn hóa
video nên phù hợp hơn cho lần chuẩn bị chính thức.

## 4. Chạy trên macOS để phát triển

Upstream LiveTalking khuyến nghị CUDA cho realtime. macOS phù hợp để sửa config,
test API/orchestrator và thử WebRTC; tốc độ lip-sync phụ thuộc máy và backend
PyTorch đang dùng.

```bash
conda create -n ai-livestream python=3.12 -y
conda activate ai-livestream
pip install -r requirements.txt
pip install -r requirements-livestream.txt
cp .env.example .env
python app.py --config config.yaml --transport webrtc --model wav2lip --avatar_id host01
```

Cần đặt checkpoint `models/wav2lip.pth` và avatar trong
`data/avatars/host01` trước khi chạy. Script tiện ích tương đương nằm tại
`scripts/run_macos.sh`.

## 5. Chạy production trên VPS GPU Windows

Repo gốc đang dùng Python 3.12, PyTorch 2.9.1 và CUDA 12.8. Trong PowerShell:

Không bắt buộc cài Conda. Nếu VPS đã có Python 3.12, chạy script tự động:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_windows.ps1
.\.venv\Scripts\Activate.ps1
$env:PATH="$PWD\bin;$env:PATH"
```

Script tạo `.venv`, cài PyTorch CUDA và chép FFmpeg cục bộ vào `bin`. Các lệnh
Conda bên dưới chỉ là lựa chọn thay thế nếu máy đã có Conda.

Nếu máy chỉ có Python 3.14 và `py.exe` báo thiếu runtime 3.12, cài song song:

```powershell
py install 3.12
py -3.12 --version
```

Chạy SRS trên máy có Docker (thay IP public phù hợp):

```powershell
docker run --rm --env CANDIDATE=YOUR_PUBLIC_IP -p 1935:1935 -p 8080:8080 -p 1985:1985 -p 8000:8000/udp registry.cn-hangzhou.aliyuncs.com/ossrs/srs:5 objs/srs -c conf/rtc2rtmp
```

Sau đó chạy avatar:

```powershell
conda create -n ai-livestream python=3.12 -y
conda activate ai-livestream
pip install torch==2.9.1 torchvision==0.24.1 torchaudio==2.9.1 --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
pip install -r requirements-livestream.txt
$env:OPENAI_API_KEY="sk-..."
$env:LIVESTREAM_API_TOKEN="mot-token-dai"
python app.py --config config.yaml --transport rtcpush --model wav2lip --avatar_id host01 --push_url "http://SRS-SERVER:1985/rtc/v1/whip/?app=live&stream=avatar"
```

Kiểm tra log `inferfps` và `finalfps`; cả hai nên từ 25 trở lên. Mở TCP 8010 chỉ
cho IP cần điều khiển. RTMP và các cổng của RTMP server cũng cần được mở theo mô
hình triển khai. Không công khai `.env`, model, thư mục record hoặc API mà không
có reverse proxy/TLS.

### Hai cách đưa vào OBS

1. **RTCPush -> SRS -> RTMP (khuyến nghị khi LiveTalking và OBS ở hai máy):**
   chạy SRS ở chế độ RTC-to-RTMP, đặt `push_url` của LiveTalking về WHIP endpoint.
   Cách này tránh phải biên dịch extension `python_rtmpstream` trên Windows. Trong OBS thêm
   Media Source/VLC Video Source với URL `rtmp://RTMP-SERVER/live/avatar`. Tắt
   local file, bật tự reconnect; sau đó dùng OBS stream ra nền tảng đích.
2. **Virtual camera (cùng một máy Windows):** cài `pyvirtualcam`, OBS virtual
   camera driver và VB-CABLE. Chạy `scripts/run_windows.ps1`, thêm Video Capture
   Device tương ứng trong OBS, rồi chọn cáp âm thanh ảo làm Audio Input Capture.
   Chọn đúng `audio_output_device` trong `config.yaml` nếu máy có nhiều thiết bị.

Luồng qua SRS giữ audio/video chung nên ít sai cấu hình âm thanh hơn virtual
camera. Nếu muốn dùng `--transport rtmp` trực tiếp, hãy build extension upstream
`lipku/python_rtmpstream` với FFmpeg 6; đây không phải package PyPI thuần Python.

## 6. API điều khiển

Tất cả endpoint điều khiển dùng header:

```http
Authorization: Bearer <LIVESTREAM_API_TOKEN>
```

### Đưa comment vào hàng đợi

```bash
curl -X POST http://SERVER:8010/api/livestream/comments \
  -H "Authorization: Bearer $LIVESTREAM_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"sessionid":"0","comment_id":"yt-123","user":"An","text":"Sản phẩm A giá bao nhiêu?"}'
```

### Nói nguyên văn, kích hoạt kịch bản, xem trạng thái

```bash
python tools/livestream_client.py speak "Xin chào cả nhà" --interrupt
python tools/livestream_client.py script welcome
python tools/livestream_client.py status
python tools/livestream_client.py pause
python tools/livestream_client.py resume
```

Các endpoint:

| Method | Path | Mục đích |
|---|---|---|
| POST | `/api/livestream/comments` | LLM trả lời comment, ưu tiên cao nhất |
| POST | `/api/livestream/speak` | Nói nguyên văn |
| POST | `/api/livestream/scripts/trigger` | Chạy kịch bản theo `script_id` |
| POST | `/api/livestream/pause` | Tạm dừng lấy item mới |
| POST | `/api/livestream/resume` | Tiếp tục |
| GET | `/api/livestream/status` | Queue, item hiện tại, lỗi gần nhất |
| GET | `/api/livestream/products` | Kiểm tra catalog đã nạp |

Các API điều khiển gốc `/human`, `/humanaudio`, `/record`, `/interrupt_talk`,
`/set_audiotype`, `/api/avatar/*` và `/api/admin/*` cũng được bảo vệ bằng cùng
Bearer token. Muốn chạy cục bộ không token, đặt `allow_unauthenticated: true`;
không dùng tùy chọn này trên VPS public.

## 7. Gắn nguồn comment thật

Bộ công cụ không đăng nhập nền tảng livestream. Tiến trình connector chỉ cần:

1. Nhận comment từ API/webhook/SDK chính thức của nền tảng.
2. Tạo `comment_id` ổn định.
3. POST nội dung vào `/api/livestream/comments`.
4. Nếu endpoint trả `duplicate: true`, không gửi lại.

Cách tách này giữ token TikTok/YouTube/Facebook ngoài tiến trình render GPU và
cho phép thay connector mà không động vào pipeline avatar.

## 8. Kiểm thử

Các test orchestration không cần GPU hay API key:

```bash
python -m pytest -q tests/test_livestream.py
```

Test end-to-end cần checkpoint, avatar, FFmpeg và GPU. Chỉ chế độ OpenAI mới cần
API key. Có thể gọi `/api/livestream/status` để xem lỗi gần nhất nếu avatar không nói.

Ở chế độ dummy, OpenAI key không cần thiết. Sau khi server và session `0` đã
chạy, tạo trực tiếp một MP4 kiểm thử TTS/lip-sync bằng hai terminal. Terminal 1:

```bash
python app.py --config config.yaml --transport null --model wav2lip --avatar_id host01
```

Terminal 2:

```bash
python tools/render_lipsync_video.py \
  "Xin chào, đây là video thử nghiệm đồng bộ khẩu hình." \
  --output output/lipsync-demo.mp4
```
