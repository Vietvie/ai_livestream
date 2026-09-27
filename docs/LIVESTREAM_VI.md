# Bộ công cụ AI livestream realtime (không giao diện)

Đây là lớp điều phối bổ sung trên LiveTalking. Luồng chạy chính:

```text
Comment/API -> hàng đợi ưu tiên -> OpenAI Responses API -> TTS
            -> Wav2Lip/MuseTalk -> SRT/UDP/RTMP -> OBS

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
- Xuất SRT/UDP MPEG-TS, WebRTC, RTMP hoặc virtual camera; có thể ghi MP4 bằng
  API gốc LiveTalking.
- API điều khiển có Bearer token, phù hợp để bộ đọc comment TikTok/Facebook/
  YouTube ở tiến trình khác gọi vào.

## 2. Chuẩn bị dữ liệu

### Chế độ dummy và API key

Mặc định `openai.provider: dummy`, hệ thống tạo lời mẫu cục bộ và **không cần
OpenAI API key**. Chế độ này dùng để ưu tiên kiểm tra TTS, lip-sync, ghi MP4 và
đường truyền OBS. Khi muốn bật LLM thật, đổi `provider: openai` rồi điền key.
TTS mặc định là OmniVoice chạy cục bộ bằng model tiếng Việt
`splendor1811/omnivoice-vietnamese`. EdgeTTS vẫn có thể chọn bằng
`--tts edgetts`; SAPI chỉ nên dùng để kiểm tra nhanh vì Windows VPS thường
không cài sẵn giọng tiếng Việt.

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

### Tùy chọn chất lượng cao hơn: MuseTalk 1.5

MuseTalk 1.5 tái tạo vùng miệng bằng mô hình diffusion/UNet nên thường tự
nhiên hơn Wav2Lip, nhưng dùng nhiều VRAM hơn và FPS thấp hơn. Dữ liệu avatar
MuseTalk có thêm `latents.pt`, `mask/` và `mask_coords.pkl`, vì vậy không dùng
chung thư mục avatar Wav2Lip. Giữ `host01` làm bản dự phòng và tạo ID mới:

```powershell
cd C:\AI_LIVESTREAM
$env:PATH="$PWD\bin;$env:PATH"
.\.venv\Scripts\python.exe .\tools\prepare_avatar.py .\avatar.mp4 `
  --avatar-id host01_muse `
  --model musetalk `
  --landmark-backend fan `
  --bbox-shift 0 `
  --musetalk-version v15
```

Lần đầu chạy, chương trình tự tải các checkpoint MuseTalk, VAE, Whisper và face
model còn thiếu từ Hugging Face. Quá trình tạo avatar chỉ cần chạy một lần và
có thể mất vài phút. Sau khi xuất hiện
`data\avatars\host01_muse\latents.pt`, chạy server:

```powershell
$env:LIVESTREAM_API_TOKEN="local-test-token"
.\.venv\Scripts\python.exe app.py `
  --config config.yaml `
  --transport null `
  --model musetalk `
  --avatar_id host01_muse `
  --batch_size 4 `
  --max_session 1 `
  --tts omnivoice
```

Tạo video thử ở terminal thứ hai, không cần kích hoạt `Activate.ps1`:

```powershell
$env:LIVESTREAM_API_TOKEN="local-test-token"
.\.venv\Scripts\python.exe .\tools\render_lipsync_video.py `
  --output .\output\musetalk-omnivoice.mp4
```

`fan` dùng 68 điểm landmark để tạo crop đúng hình học mà MuseTalk đã
huấn luyện; chế độ `detector` chỉ là fallback khi không thể cài FAN. Lần đầu
dùng FAN sẽ tự tải checkpoint landmark. Nếu đường ghép quanh cằm chưa
đẹp, tạo một avatar ID mới và thử `--bbox-shift -5` hoặc
`--bbox-shift 5`. Không ghi đè avatar đang hoạt động trong lúc server chạy.
Với RTX 5060 Ti, bắt đầu bằng `batch_size 4`; chỉ tăng lên `8` khi
`nvidia-smi` cho thấy còn VRAM và log `inferfps` vẫn ổn định.

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

Checkpoint chính thức `models/wav2lip.pth` được tải và kiểm tra SHA-256 tự động
khi chọn Wav2Lip lần đầu. Avatar trong `data/avatars/host01` vẫn cần được chuẩn
bị trước khi chạy. Script tiện ích tương đương nằm tại `scripts/run_macos.sh`.

## 5. Chạy production trên VPS GPU Windows

Repo gốc đang dùng Python 3.12, PyTorch 2.9.1 và CUDA 12.8. Trong PowerShell:

Không bắt buộc cài Conda. Nếu VPS đã có Python 3.12, chạy script tự động:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\setup_windows.ps1
$env:PATH="$PWD\bin;$env:PATH"
```

Script tạo `.venv`, cài PyTorch CUDA, OmniVoice, dependency MuseTalk và chép
FFmpeg cục bộ vào `bin`. Model được tải khi dùng lần đầu: MuseTalk tải khi
chuẩn bị avatar, Wav2Lip tải khi khởi động backend Wav2Lip/Way2Lip, còn
OmniVoice tải khi nhận câu đầu tiên. Không cần kích hoạt `Activate.ps1` và
không cần chạy script setup model riêng.

### Tự tải và thử OmniVoice tiếng Việt

Sau khi `setup_windows.ps1` chạy thành công, chạy toàn bộ luồng. Lần tạo câu
đầu tiên sẽ tự tải OmniVoice từ Hugging Face và lâu hơn các lần sau:

```powershell
$env:PATH="$PWD\bin;$env:PATH"
$env:LIVESTREAM_API_TOKEN="local-test-token"
.\.venv\Scripts\python.exe app.py `
  --config config.yaml `
  --transport null `
  --model wav2lip `
  --avatar_id host01 `
  --batch_size 8 `
  --max_session 1 `
  --tts omnivoice
```

Ở terminal thứ hai, ghi một video lip-sync thử nghiệm:

```powershell
.\.venv\Scripts\python.exe tools\render_lipsync_video.py `
  "Xin chào, đây là video thử nghiệm OmniVoice tiếng Việt." `
  --output output\omnivoice-lipsync.mp4
```

Model được giữ trong VRAM để giảm độ trễ giữa các câu. Nếu thiếu VRAM, giảm
`batch_size` của Wav2Lip xuống `4`; có thể giảm `omnivoice_num_step` xuống `8`
để ưu tiên tốc độ. Không nên đặt OmniVoice chạy CPU cho livestream realtime.

Muốn clone một giọng đã được phép sử dụng, chuẩn bị WAV sạch 3–10 giây và phần
chép lời khớp chính xác rồi sửa:

```yaml
omnivoice_ref_audio: 'data/voices/host.wav'
omnivoice_ref_text: 'Nội dung được nói chính xác trong đoạn âm thanh tham chiếu.'
omnivoice_instruct: ''
```

Hoặc không cần cấu hình: đặt một mẫu giọng tiếng Việt đã được phép
sử dụng tại `<project>/voice.wav`. Khi khởi động với `--tts omnivoice`,
hệ thống tự chuẩn hóa audio, dùng `vinai/PhoWhisper-small` để chép lời,
cache kết quả trong `data/voices/` và bật voice clone. Thay đổi `voice.wav`
sẽ tự làm mới cache ở lần chạy kế tiếp.

Trên Windows có thể truyền trực tiếp hai tham số cho script OBS:

```powershell
.\scripts\run_obs_windows.ps1 `
  -VoiceRefAudio ".\data\voices\host.wav" `
  -VoiceRefText "Nội dung được nói chính xác trong file mẫu."
```

Nếu Windows PowerShell hiển thị tiếng Việt thành dấu `?`, lưu transcript
trong file UTF-8 và thay `-VoiceRefText` bằng
`-VoiceRefTextFile ".\data\voices\host.txt"`.

Khi server đang chạy, endpoint có xác thực
`POST /api/livestream/voice-clone` nhận multipart gồm `file`, `ref_text`,
`sessionid` và `consent=true`. Dùng `GET` cùng endpoint để xem trạng thái,
hoặc `DELETE` để trở về giọng mặc định. File upload tối đa 25 MB;
audio phải là WAV dài 3–30 giây.

Chỉ clone giọng khi có sự đồng ý của người sở hữu. Đồng thời cần kiểm tra giấy
phép của checkpoint/dataset OmniVoice trước khi dùng cho hoạt động thương mại.

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

### Đưa luồng sang OBS

1. **SRT qua Internet (khuyến nghị cho Ubuntu xử lý và OBS ở máy khác):**
   máy Ubuntu chạy SRT ở chế độ `listener`; OBS là `caller` chủ động kết nối tới
   Ubuntu. Cách bố trí này chỉ cần mở một cổng UDP trên Ubuntu, không cần mở cổng
   hay port-forward ở máy OBS. SRT truyền H.264 + AAC chung trong MPEG-TS, có
   phục hồi mất gói và phù hợp hơn UDP thuần qua Internet.

   Trên Ubuntu:

   ```bash
   export LIVESTREAM_API_TOKEN='mot-token-dai'
   export LIVESTREAM_SRT_PORT=10080
   # Tùy chọn nhưng nên dùng khi đi qua Internet (10-79 ký tự URL-safe):
   export LIVESTREAM_SRT_PASSPHRASE='ThayBangMatKhauDai123'
   chmod +x scripts/run_obs_remote_ubuntu.sh
   ./scripts/run_obs_remote_ubuntu.sh
   ```

   Mở inbound **UDP 10080** trong firewall/security group của Ubuntu. Trong OBS
   ở máy khác, thêm **Media Source**, bỏ chọn **Local File**, đặt **Input** là:

   ```text
   srt://PUBLIC_IP_UBUNTU:10080?mode=caller&transtype=live&latency=500000&passphrase=ThayBangMatKhauDai123&pbkeylen=16
   ```

   Đặt **Input Format** là `mpegts`, bật tự khởi động lại phát khi source trở
   thành active. Nếu không dùng passphrase, bỏ hai tham số `passphrase` và
   `pbkeylen` ở cả hai phía. `latency` tính bằng microsecond; bắt đầu với
   `500000` (0,5 giây), giảm về `300000` khi đường truyền tốt hoặc tăng lên
   `1000000` khi có giật/mất gói. OBS nên được mở sau khi tiến trình Ubuntu đã
   báo đang chờ SRT; nếu OBS mất kết nối, transport sẽ mở lại listener.

   Kiểm tra đường truyền mà chưa tải model AI:

   ```bash
   .venv/bin/python tools/test_obs_stream.py \
     --url 'srt://0.0.0.0:10080?mode=listener&transtype=live&latency=500000&pkt_size=1316'
   ```

   Máy OBS dùng URL caller tương ứng. Luồng kiểm tra hiển thị card hình và âm
   440 Hz. Một listener trực tiếp phục vụ một OBS; nếu cần nhiều OBS hoặc cần
   phân phối qua nhiều mạng, đặt MediaMTX/SRT relay ở giữa.

2. **OBS Media Source qua UDP (khi OBS chạy cùng máy xử lý):**
   transport `obs` mã hóa H.264 + AAC thành một luồng MPEG-TS hoàn chỉnh tại
   `udp://127.0.0.1:23000`. Trong OBS thêm **Media Source**, bỏ chọn
   **Local File**, đặt **Input** là `udp://127.0.0.1:23000`, đặt
   **Input Format** là `mpegts` nếu OBS không tự nhận. Cách này không cần
   virtual camera, VB-CABLE hoặc SRS và giữ audio/video trong cùng luồng.

   ```powershell
   $env:LIVESTREAM_API_TOKEN="local-test-token"
   powershell.exe -NoProfile -ExecutionPolicy Bypass `
     -File .\scripts\run_obs_windows.ps1
   ```

   Có thể kiểm tra riêng kết nối OBS bằng card thử và âm 440 Hz trước khi tải
   model AI: `.\.venv\Scripts\python.exe .\tools\test_obs_stream.py`.

3. **RTCPush -> SRS -> RTMP (phương án có media server):**
   chạy SRS ở chế độ RTC-to-RTMP, đặt `push_url` của LiveTalking về WHIP endpoint.
   Cách này tránh phải biên dịch extension `python_rtmpstream` trên Windows. Trong OBS thêm
   Media Source/VLC Video Source với URL `rtmp://RTMP-SERVER/live/avatar`. Tắt
   local file, bật tự reconnect; sau đó dùng OBS stream ra nền tảng đích.
4. **Virtual camera (cùng một máy Windows):** cài `pyvirtualcam`, OBS virtual
   camera driver và VB-CABLE. Chạy `scripts/run_windows.ps1`, thêm Video Capture
   Device tương ứng trong OBS, rồi chọn cáp âm thanh ảo làm Audio Input Capture.
   Chọn đúng `audio_output_device` trong `config.yaml` nếu máy có nhiều thiết bị.

Luồng qua SRS giữ audio/video chung nên ít sai cấu hình âm thanh hơn virtual
camera. Nếu muốn dùng `--transport rtmp` trực tiếp, hãy build extension upstream
`lipku/python_rtmpstream` với FFmpeg 6; đây không phải package PyPI thuần Python.

WebRTC vẫn hữu ích cho trang xem trước hoặc điều khiển tương tác cần độ trễ cực
thấp. Với OBS chạy dài ở máy khác, SRT là đường chính dễ vận hành hơn vì OBS có
Media Source SRT trực tiếp; không phụ thuộc Browser Source, thao tác bấm Start
hay vòng đời phiên WebRTC của trang web.

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
