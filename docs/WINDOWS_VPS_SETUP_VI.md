# Cài đặt AI Livestream trên VPS Windows RTX 5060 Ti

Tài liệu này hướng dẫn cài đặt và kiểm tra một luồng MuseTalk + OmniVoice.
UDP loopback được dùng mặc định khi OBS chạy cùng VPS; khi chuyển OBS sang máy
khác, cùng script khởi động có thể chuyển sang SRT bằng một tham số.

Quy trình không dùng Conda và không yêu cầu chạy `Activate.ps1`. Mọi lệnh
Python đều gọi trực tiếp `.venv\Scripts\python.exe` để tránh lỗi PowerShell
Execution Policy và nhầm môi trường Python.

## 1. Cấu hình thử nghiệm

- Windows VPS
- CPU Intel Core i7-12700K, 20 logical cores
- RAM 28 GB
- NVIDIA GeForce RTX 5060 Ti, VRAM 16 GB
- SSD 1.600 GB
- Mạng 1 Gbps
- Python 3.12
- PyTorch 2.9.1, CUDA runtime 12.8
- MuseTalk v1.5, `batch_size=4`
- OmniVoice tiếng Việt, float16
- Một luồng 720p, 25 fps

`CUDA 4608` trong thông tin VPS thường là 4.608 CUDA cores của GPU, không phải
phiên bản CUDA. Dự án dùng PyTorch CUDA 12.8.

## 2. Kiểm tra NVIDIA driver

Mở PowerShell:

```powershell
nvidia-smi
```

Kết quả phải có `NVIDIA GeForce RTX 5060 Ti` và khoảng 16 GB VRAM. Nếu
`nvidia-smi` không tồn tại hoặc không nhận GPU, cài NVIDIA Studio Driver mới và
khởi động lại VPS.

Tham khảo [NVIDIA Driver Installation Guide](https://docs.nvidia.com/datacenter/tesla/driver-installation-guide/).

## 3. Cài Git và Python 3.12

Nếu VPS có `winget`:

```powershell
winget install -e --id Git.Git
winget install -e --id Python.Python.3.12
```

Đóng PowerShell, mở lại rồi kiểm tra:

```powershell
git --version
py -3.12 --version
```

Nếu `winget` không có, tải Python 3.12 từ python.org. Khi cài, chọn `Add
python.exe to PATH` và `Install launcher for all users`. Không dùng Python 3.14
cho môi trường dự án này.

## 4. Clone source code

Dùng thư mục không có khoảng trắng:

```powershell
cd C:\
git clone https://github.com/Vietvie/ai_livestream.git AI_LIVESTREAM
cd C:\AI_LIVESTREAM
git checkout main
git pull origin main
```

Nếu repository riêng tư, sử dụng SSH:

```powershell
git clone git@github.com:Vietvie/ai_livestream.git C:\AI_LIVESTREAM
```

Kiểm tra phiên bản source:

```powershell
git log -1 --oneline
```

Source phải chứa commit `d0c6893` hoặc commit mới hơn.

## 5. Cài môi trường Python và PyTorch

Chạy bằng Execution Policy tạm thời, không thay đổi chính sách toàn hệ thống:

```powershell
cd C:\AI_LIVESTREAM

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\setup_windows.ps1
```

Script sẽ:

- Tạo `.venv` bằng Python 3.12.
- Cài PyTorch 2.9.1 CUDA 12.8.
- Cài các dependency của LiveTalking và lớp livestream.
- Cài package OmniVoice, Hugging Face và FAN landmark.
- Tạo `bin\ffmpeg.exe`.
- Kiểm tra GPU.

Script **không tải checkpoint MuseTalk hoặc OmniVoice**. Model nào được sử dụng
mới được tải tự động trong lần chạy đầu tiên.

PyTorch cung cấp bộ 2.9.1 CUDA 12.8 chính thức cho Windows/Python 3.12 tại
[PyTorch previous versions](https://pytorch.org/get-started/previous-versions/).

Không cần kích hoạt virtualenv. Từ đây luôn dùng:

```powershell
.\.venv\Scripts\python.exe
```

## 6. Kiểm tra CUDA và FFmpeg

```powershell
cd C:\AI_LIVESTREAM
$env:PATH="$PWD\bin;$env:PATH"
$env:PYTHONUTF8="1"
chcp 65001

.\.venv\Scripts\python.exe -c "import torch; print('PyTorch:', torch.__version__); print('CUDA:', torch.cuda.is_available()); print('CUDA runtime:', torch.version.cuda); print('GPU:', torch.cuda.get_device_name(0)); print('VRAM GB:', round(torch.cuda.get_device_properties(0).total_memory/1024**3, 1))"

ffmpeg -version
```

Kết quả mong đợi:

```text
CUDA: True
CUDA runtime: 12.8
GPU: NVIDIA GeForce RTX 5060 Ti
VRAM GB: khoảng 16
```

## 7. Cơ chế tự tải model

Không cần chạy `setup_musetalk_windows.ps1`,
`setup_omnivoice_windows.ps1` hoặc tải checkpoint thủ công.

- Khi chạy `prepare_avatar.py --model musetalk` lần đầu, chương trình tự tải
  MuseTalk v1.5, VAE, Whisper, face parsing và face detector còn thiếu.
- Khi chọn `wav2lip` hoặc alias `way2lip` lần đầu, server tự tải checkpoint
  Wav2Lip 256 chính thức (~205 MB) vào `models\wav2lip.pth`, sau đó kiểm tra
  kích thước và SHA-256 trước khi nạp model.
- Khi TTS nhận câu nói đầu tiên, OmniVoice tự tải model tiếng Việt còn thiếu.
- Những lần sau chương trình dùng cache/model trên SSD và không tải lại.
- Nếu download bị gián đoạn, chạy lại đúng lệnh đang dùng; chương trình chỉ tải
  file còn thiếu.

Sau khi `setup_windows.ps1` hoàn thành, chỉ cần kiểm tra dependency:

```powershell
.\.venv\Scripts\python.exe -m pip check
```

Kết quả nên là `No broken requirements found.` Model được tải sau, ở bước thực
sự cần tới nó.

## 8. Copy và chuẩn bị video avatar

Copy video vào:

```text
C:\AI_LIVESTREAM\avatar.mp4
```

Kiểm tra:

```powershell
Test-Path C:\AI_LIVESTREAM\avatar.mp4
```

Tạo avatar MuseTalk cho video dọc. Lần chạy đầu tự tải checkpoint nên có thể mất
thêm vài phút và cần kết nối Internet tới Hugging Face:

```powershell
cd C:\AI_LIVESTREAM
$env:PATH="$PWD\bin;$env:PATH"

.\.venv\Scripts\python.exe .\tools\prepare_avatar.py .\avatar.mp4 `
  --avatar-id host01_muse_fan `
  --model musetalk `
  --landmark-backend fan `
  --bbox-shift 0 `
  --musetalk-version v15
```

Nếu video ngang 16:9, thêm hai tham số:

```powershell
  --width 1280 `
  --height 720
```

Kiểm tra kết quả:

```powershell
Test-Path .\data\avatars\host01_muse_fan\latents.pt
Test-Path .\data\avatars\host01_muse_fan\coords.pkl
Test-Path .\data\avatars\host01_muse_fan\mask_coords.pkl
```

Tất cả phải trả về `True`.

## 9. Chạy thử TTS và lip-sync thành MP4

Trong PowerShell thứ nhất:

```powershell
cd C:\AI_LIVESTREAM
$env:PATH="$PWD\bin;$env:PATH"
$env:PYTHONUTF8="1"
$env:LIVESTREAM_API_TOKEN="local-test-token"

.\.venv\Scripts\python.exe app.py `
  --config config.yaml `
  --transport null `
  --model musetalk `
  --avatar_id host01_muse_fan `
  --batch_size 4 `
  --max_session 1 `
  --tts omnivoice
```

Lần đầu server nhận câu nói, OmniVoice sẽ tự tải model tiếng Việt. Chờ log có
các dòng tương đương:

```text
Using cuda for inference
OmniVoice ready
start inference
start http server
```

Trong PowerShell thứ hai:

```powershell
cd C:\AI_LIVESTREAM
$env:LIVESTREAM_API_TOKEN="local-test-token"
$env:PYTHONUTF8="1"

.\.venv\Scripts\python.exe .\tools\render_lipsync_video.py `
  "Xin chào, đây là video thử nghiệm hệ thống livestream trí tuệ nhân tạo bằng tiếng Việt." `
  --output .\output\musetalk-test.mp4
```

Mở kết quả:

```powershell
Start-Process .\output\musetalk-test.mp4
```

## 10. Chạy AI livestream bằng một lệnh

Từ bất kỳ PowerShell nào, chạy đúng một lệnh sau. Không cần kích hoạt `.venv`,
không cần khai báo lại `PATH` và không cần mở thêm terminal relay:

```powershell
powershell -ExecutionPolicy Bypass -File C:\AI_LIVESTREAM\scripts\run_obs_windows.ps1
```

Mặc định script dùng UDP local và tự thực hiện các việc sau:

- Dùng `.venv\Scripts\python.exe` đúng của dự án.
- Thêm `C:\AI_LIVESTREAM\bin` vào `PATH`.
- Giới hạn số thread CPU để MuseTalk không chiếm 100% CPU.
- Dùng `h264_nvenc`, MuseTalk, OmniVoice 8 bước và `batch_size=4`.
- Tiến khẩu hình MuseTalk 1 frame (40 ms) để bù độ trễ giải mã video OBS.
- Xuất MPEG-TS trực tiếp tới UDP loopback `23000`.
- In sẵn URL cần nhập trong OBS.

### So sánh Wav2Lip (`way2lip`) với MuseTalk

LiveTalking đặt tên backend gốc là `wav2lip`. Script cũng chấp nhận
`way2lip` là tên alias thử nghiệm. Cả hai dùng cùng checkpoint; nếu
`models\wav2lip.pth` chưa có, server tự tải và kiểm tra checkpoint trong lần
khởi động đầu tiên. Chỉ avatar Wav2Lip `host01` cần được chuẩn bị trước.

Chạy Wav2Lip với avatar `host01`:

```powershell
powershell -ExecutionPolicy Bypass -File C:\AI_LIVESTREAM\scripts\run_obs_windows.ps1 -Model way2lip -AvatarId host01
```

Chuyển lại MuseTalk:

```powershell
powershell -ExecutionPolicy Bypass -File C:\AI_LIVESTREAM\scripts\run_obs_windows.ps1 -Model musetalk -AvatarId host01_muse_fan
```

Cả hai lệnh mặc định xuất UDP local tới `127.0.0.1:23000`, vì vậy
không cần thay Media Source trong OBS. `-LipSyncOffsetFrames` chỉ hiệu lực
với MuseTalk.

### Dùng voice clone với OmniVoice

Chỉ clone giọng khi có sự đồng ý rõ ràng của người sở hữu. Chuẩn bị
một file WAV sạch dài 3–10 giây, chỉ có một người nói, không nhạc nền;
phần chép lời phải khớp chính xác với file.

Cách khuyến nghị không cần nhập transcript: chỉ copy file vào đúng vị trí:

```text
C:\AI_LIVESTREAM\voice.wav
```

Sau đó chạy script OBS bình thường, không truyền tham số voice:

```powershell
powershell -ExecutionPolicy Bypass -File C:\AI_LIVESTREAM\scripts\run_obs_windows.ps1 `
  -Model way2lip `
  -AvatarId host01
```

Lần chạy đầu, code tự thực hiện toàn bộ quy trình:

1. Đọc `voice.wav`, trộn về mono, cắt im lặng đầu/cuối và chuẩn hóa 16 kHz.
2. Tự tải `vinai/PhoWhisper-small` và chép lời tiếng Việt cục bộ.
3. Lưu audio và transcript vào `data\voices\auto-voice.*`.
4. Giải phóng tiến trình ASR, sau đó mới nạp Wav2Lip/MuseTalk và OmniVoice.
5. Cache kết quả; những lần sau không chạy ASR lại. Khi thay `voice.wav`,
   cache tự động được tạo lại.

Lần đầu sẽ mất thêm thời gian tải PhoWhisper. Các cách khai báo
`-VoiceRefAudio` và transcript bên dưới chỉ dùng khi muốn ghi đè kết quả ASR.

Thử riêng giọng clone trước khi livestream:

```powershell
.\.venv\Scripts\python.exe .\tools\test_omnivoice_tts.py `
  --ref-audio ".\data\voices\host.wav" `
  --ref-text "Nội dung được nói chính xác trong file mẫu." `
  --text "Xin chào, đây là bài kiểm tra giọng nói đã sao chép." `
  --num-step 8 `
  --output ".\output\voice-clone-test.wav"

Start-Process .\output\voice-clone-test.wav
```

Chạy OBS local với giọng clone:

```powershell
powershell -ExecutionPolicy Bypass -File C:\AI_LIVESTREAM\scripts\run_obs_windows.ps1 `
  -Model way2lip `
  -AvatarId host01 `
  -VoiceRefAudio "C:\AI_LIVESTREAM\data\voices\host.wav" `
  -VoiceRefText "Nội dung được nói chính xác trong file mẫu."
```

Với Windows PowerShell 5.1, nên lưu transcript thành file UTF-8
`data\voices\host.txt` rồi dùng `-VoiceRefTextFile` để tránh tiếng Việt
bị biến thành dấu `?`:

```powershell
powershell -ExecutionPolicy Bypass -File C:\AI_LIVESTREAM\scripts\run_obs_windows.ps1 `
  -Model way2lip `
  -AvatarId host01 `
  -VoiceRefAudio "C:\AI_LIVESTREAM\data\voices\host.wav" `
  -VoiceRefTextFile "C:\AI_LIVESTREAM\data\voices\host.txt"
```

Có thể đổi giọng cho session `0` khi server đang chạy qua API có token:

```powershell
curl.exe -X POST "http://127.0.0.1:8010/api/livestream/voice-clone" `
  -H "Authorization: Bearer local-test-token" `
  -F "sessionid=0" `
  -F "consent=true" `
  -F "ref_text=Nội dung được nói chính xác trong file mẫu." `
  -F "file=@C:\AI_LIVESTREAM\data\voices\host.wav"
```

Xem trạng thái hoặc trở về giọng mặc định:

```powershell
curl.exe "http://127.0.0.1:8010/api/livestream/voice-clone?sessionid=0" `
  -H "Authorization: Bearer local-test-token"

curl.exe -X DELETE "http://127.0.0.1:8010/api/livestream/voice-clone?sessionid=0" `
  -H "Authorization: Bearer local-test-token"
```

### OBS đang chạy trên cùng VPS

Trong OBS thêm **Media Source**:

- Bỏ chọn **Local File**.
- Đặt **Input** là:

```text
udp://127.0.0.1:23000
```

- Đặt **Input Format** là `mpegts`.
- Bật khởi động lại phát khi source trở thành active.

Không cần mở firewall và không dùng FFmpeg relay khi OBS chạy trên cùng VPS.

### Hiệu chỉnh khẩu hình theo thời gian

Mặc định script dùng `-LipSyncOffsetFrames 1`, tức khẩu hình được tiến 40 ms.
Không cần tạo lại avatar khi thay đổi giá trị này:

- Nếu miệng vẫn chậm hơn tiếng, thử `2` (tiến 80 ms).
- Nếu miệng chạy trước tiếng, thử `0`; nếu vẫn sớm, thử `-1` (trễ 40 ms).

Ví dụ:

```powershell
powershell -ExecutionPolicy Bypass -File C:\AI_LIVESTREAM\scripts\run_obs_windows.ps1 -LipSyncOffsetFrames 2
```

Mỗi lần chỉ thay một frame rồi nghe câu có nhiều âm đóng/mở môi như
“ba, ma, pha, môi, mua” để chọn giá trị chính xác nhất.

### OBS chạy ở máy khác

Khi chuyển OBS sang máy khác, chạy script ở chế độ SRT:

```powershell
powershell -ExecutionPolicy Bypass -File C:\AI_LIVESTREAM\scripts\run_obs_windows.ps1 -ObsMode srt
```

Sau đó mở UDP `10080` trong Windows Firewall:

```powershell
New-NetFirewallRule `
  -DisplayName "AI Livestream SRT UDP 10080" `
  -Direction Inbound `
  -Protocol UDP `
  -LocalPort 10080 `
  -Action Allow
```

Nếu nhà cung cấp VPS có firewall/security group riêng, mở thêm UDP `10080` ở
trang quản trị VPS. Trên OBS máy khác dùng **Media Source** với Input:

```text
srt://IP_PUBLIC_VPS:10080?mode=caller&transtype=live&latency=500000&passphrase=MatKhauSRT123456&pbkeylen=16
```

Input Format vẫn là `mpegts`. Không cần thay đổi các tham số model/TTS. Listener này
phục vụ một OBS tại một thời điểm; hãy đóng Media Source local trước khi kết
nối từ OBS máy khác.

Đổi `MatKhauSRT123456` trước khi dùng thật bằng tham số `-SrtPassphrase`:

```powershell
powershell -ExecutionPolicy Bypass -File C:\AI_LIVESTREAM\scripts\run_obs_windows.ps1 -ObsMode srt -SrtPassphrase "MatKhauMoiToiThieu10KyTu"
```

## 11. Gửi câu nói thử qua API

Mở PowerShell khác:

```powershell
$headers = @{
  Authorization = "Bearer local-test-token"
}

$body = @{
  sessionid = "0"
  text = "Xin chào mọi người, đây là buổi livestream thử nghiệm đầu tiên."
  interrupt = $true
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8010/api/livestream/speak" `
  -Headers $headers `
  -ContentType "application/json; charset=utf-8" `
  -Body $body
```

Kiểm tra trạng thái:

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8010/api/livestream/status" `
  -Headers $headers
```

Chế độ mặc định dùng LLM dummy nên chưa cần OpenAI API key.

## 12. Theo dõi tài nguyên

Mở PowerShell khác:

```powershell
nvidia-smi -l 2
```

Một lần test đạt yêu cầu khi:

- VRAM không vượt sát 16 GB.
- Log `actual avg infer fps` cao hơn 25.
- OBS không giật hình hoặc mất âm thanh.
- Lip-sync bắt đầu trong thời gian chấp nhận được.
- Không xuất hiện `CUDA out of memory`.

Nếu thiếu VRAM, giảm `--batch_size 4` xuống `--batch_size 2`. Sau khi một luồng
hoạt động ổn định mới bắt đầu thử kiến trúc đa luồng.

## 13. Lỗi thường gặp

### `conda` không tồn tại

Không dùng Conda. Luôn gọi `.\.venv\Scripts\python.exe`.

### `Activate.ps1 cannot be loaded`

Không cần kích hoạt môi trường. Nếu phải chạy script PowerShell, dùng:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\TEN_SCRIPT.ps1
```

### `ModuleNotFoundError: flask` hoặc `requests`

Đang dùng nhầm Python hệ thống. Chạy bằng:

```powershell
.\.venv\Scripts\python.exe app.py
```

### `ffmpeg is required and was not found in PATH`

```powershell
$env:PATH="$PWD\bin;$env:PATH"
ffmpeg -version
```

### `CUDA: False`

Kiểm tra `nvidia-smi`, sau đó cài lại đúng PyTorch CUDA 12.8:

```powershell
.\.venv\Scripts\python.exe -m pip install --force-reinstall `
  torch==2.9.1 torchvision==0.24.1 torchaudio==2.9.1 `
  --index-url https://download.pytorch.org/whl/cu128
```

### SRT báo `Protocol not found`

Một số wheel PyAV cho Windows không chứa `libsrt`, ngay cả khi `ffmpeg.exe`
trên máy có hỗ trợ SRT. Transport OBS sẽ tự nhận lỗi này và mở relay FFmpeg
qua UDP loopback; không cần cài lại PyAV và không mã hóa video/audio lần hai.

Đảm bảo FFmpeg có SRT và thư mục `bin` đang trong `PATH`:

```powershell
$env:PATH="$PWD\bin;$env:PATH"
ffmpeg -protocols | Select-String srt
```

Khi fallback hoạt động, log sẽ có dòng
`[OBS] FFmpeg SRT relay started on local TCP port 23001`. Nếu port này đang
được chương trình khác sử dụng, thêm `--obs_srt_relay_port 23002` vào lệnh chạy.

### `h264_nvenc` không khả dụng

Giữ `--obs_video_encoder libx264`. CPU i7-12700K đủ để thử một luồng 720p25.

### OmniVoice hoặc MuseTalk hết VRAM

- Giảm `--batch_size` từ 4 xuống 2.
- Giảm `omnivoice_num_step` trong `config.yaml` từ 16 xuống 8.
- Chỉ chạy một session khi kiểm tra ban đầu.
