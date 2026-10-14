# Driver Monitor — học và xây dựng từ đầu

## Chạy ứng dụng tích hợp với ESP32

`app.py` là điểm chạy chính: MediaPipe theo dõi mắt, miệng và tư thế đầu;
bộ quy tắc thời gian đánh giá nguy cơ và điều khiển buzzer GPIO14 qua CDC.
Firmware tương thích nằm ở `/home/cobalt/Documents/PlatformIO/Projects/esp-webcam`.
Ứng dụng dùng firmware đang nạp, không tự build hoặc flash.

```sh
cd /home/cobalt/Projects/driver-monitor
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -B app.py --check
.venv/bin/python -B app.py --hardware-test --headless
.venv/bin/python -B app.py
```

Trên Linux, mặc định tìm đúng camera và CDC của ESP32 serial `AI-DETECT-001`
qua `/dev/v4l/by-id` và `/dev/serial/by-id`, không dùng webcam tích hợp.
Đóng ứng dụng đang giữ camera hoặc CDC trước khi chạy. Có thể chọn rõ thiết bị:

```sh
.venv/bin/python -B app.py --camera /dev/video5 --alarm-port /dev/ttyACM0
.venv/bin/python -B app.py --camera 0 --alarm-port none
.venv/bin/python -B app.py --headless --seconds 30
```

Windows: chỉ định camera index và `--alarm-port COMxx`. Không tự suy ra COM
từ cổng dùng để nạp firmware. Số `/dev/video*` và COM có thể đổi sau khi cắm lại.

Giữ mắt mở, miệng khép và đầu nhìn thẳng trong 8 giây quan sát hợp lệ để
hiệu chỉnh; cần ít nhất 60 mẫu. Nếu đầu chuyển động nhiều, ứng dụng thông báo
và tự bắt đầu lại hiệu chỉnh, giữ cảnh báo tắt. Q/Esc thoát, C hiệu chỉnh lại, Ctrl+C dừng.
Mặc định ứng dụng chạy tới khi dừng, nhận HD/MJPG 1280×720 và yêu cầu 30 FPS;
FPS thực tế phụ thuộc camera và xử lý. Camera đọc trên luồng riêng và chỉ giữ
frame mới nhất. Thời lượng dùng timestamp PC nhận frame, không phải timestamp cảm biến.

| Dấu hiệu | Mặc định |
|---|---|
| Hai mắt nhắm liên tục | Đạt 1,5 giây: nghi ngủ gật, cảnh báo nguy hiểm |
| Miệng / dấu hiệu ngáp | Hiển thị mở/khép ngay khi quan sát hợp lệ, độc lập với mắt; không kiểm tra thời lượng hoặc đếm lần |
| Giữ nghiêng đầu / nhìn đường | Chỉ hiển thị góc và thời lượng; không tự tăng nguy cơ hoặc bật còi |
| Giữ gục trước | Quan sát pitch ≤5° trước, cúi ≥10° liên tục 0,75 giây: cảnh báo trong khi còn giữ cúi hợp lệ |
| Gục trước rồi dựng | Cúi ≥4° rồi về ≤2° trong 0,03–4 giây: nhận và hiển thị nodding; không tự bật còi |
| Sụp sang bên rồi bật lại | Nhận và hiển thị chuyển động theo ngưỡng hiện có; không tự bật còi |

Góc tính tương đối với đầu trung tính đã hiệu chỉnh. Nếu cúi xuống mà pitch
hiển thị âm, chạy lại với `--pitch-sign -1`. Tùy chỉnh, ví dụ:

```sh
.venv/bin/python -B app.py --eye-closed-seconds 1
.venv/bin/python -B app.py --nod-enter 4 --nod-exit 2 --nod-min 0.03 --nod-max 4 --jerk-speed 60
.venv/bin/python -B app.py --head-hold-seconds 0.75
.venv/bin/python -B app.py --lateral-drop-angle 15 --lateral-return-angle 8 --lateral-baseline-seconds 0.5
.venv/bin/python -B app.py --help
```

Các dấu hiệu là quy tắc quan sát, chưa có model học phân loại buồn ngủ hoặc
xác nhận microsleep sinh lý. Phần miệng chỉ hiển thị mở/khép theo MAR và
ghi thay đổi trạng thái, không dùng mốc 2,8 giây hay bộ đếm 4 lần/120 giây.
Mở miệng khi nói hoặc hát cũng có thể xuất hiện dấu hiệu này; không tự xác
nhận đó là ngáp thật. Mắt mở/nhắm không chặn quan sát miệng khi miệng và
pose còn hợp lệ. Các tùy chọn `--yawn-min`, `--yawn-max`, `--yawn-window`
và `--yawn-count` đã được bỏ khỏi CLI của `app.py`.

Gục trước và gục bên được theo dõi độc lập, đều cần quan sát tư thế nghỉ trước
khi bắt đầu. Tư thế nghỉ gục bên là đoạn roll ổn định 0,5 giây với biên độ
dao động ≤3°; mốc này giữ nguyên trong chu kỳ. Vì vậy đầu vốn đang nghiêng
vẫn có thể gục thêm rồi bật lại, còn giữ nghiêng lâu không bật còi. Gục
quá ngắn không hoàn thành chu kỳ. Chỉ gục bên yêu cầu vận tốc bật lại
≥60°/giây (`--jerk-speed`); cúi trước rồi trở lại chậm hơn vẫn được nhận
nếu hoàn thành trong 4 giây. Giữ cúi trước ≥10° đủ 0,75 giây
(`--head-hold-seconds`) cũng cảnh báo mà không cần dựng lại.
Các chuỗi vẫn được nhận và ghi log nhưng không tạo đợt còi.

Nodding dùng bộ lọc pitch riêng với hằng số thời gian 0,03 giây
(`--nod-filter-tau`) để hạn chế làm mất cú gật ngắn. Màn hình hiển thị riêng
`Nodding pitch`; CSV có cột `nod_pitch_deg`. Ngưỡng nodding 4°/2° được tách
khỏi cảnh báo giữ gục: `--head-drop-angle 10`, `--head-rest-angle 5`,
`--head-hold-seconds 0.75`. Nhận nodding nhạy hơn không bật buzzer ở 4°.

Bản trước (ngưỡng 6°/3°) đã qua 111 kiểm thử, gồm cú gật nhẹ 7° qua bộ lọc ở 10/15/30
FPS. Lượt thử ESP32 30 giây đạt 16,10 FPS và nhận 2 nodding thực tế, với
đỉnh pitch khoảng 7,96° và 10,69°. Giữ riêng điều kiện gục bên 0,2–2,5
giây; chỉ tăng độ nhạy nhận gật đầu về trước.

Trong `app.py`, sự kiện `nod_candidate` đã được bộ đo xác nhận là nguồn
xác nhận quan sát gật đầu về trước. Không yêu cầu một bộ khác xác nhận lại vận tốc
hay thời gian giữ cúi. Ứng dụng kiểm tra mốc bắt đầu, thời lượng, pose liên
tục và điều kiện yaw của toàn bộ sự kiện, rồi phát `forward_head_bob`.
Một sự kiện chỉ kích hoạt một lần. Màn hình hiện `NODDING CONFIRMED` và
terminal hiện `NODDING CONFIRMED (observation only)`; nếu bị loại, hiện
`NODDING REJECTED` với lý do. Trạng thái `Buzzer` hiển thị riêng quyết định bật còi.

Chỉ xét chuỗi đầu khi pose hợp lệ, |yaw| ≤35° và yaw không lệch quá 10°
so với lúc bắt đầu. Quay lớn, mất pose hoặc gap hủy chuỗi và yêu cầu quan
sát lại tư thế nghỉ. `--head-max-yaw` và `--head-yaw-change` chỉnh hai mốc
này. Điều kiện yaw không tắt cảnh báo nhắm mắt kéo dài.
`--tilt-angle` chỉ đổi phân vùng góc hiển thị; `--tilt-seconds` được giữ để
tương thích câu lệnh cũ và không còn ảnh hưởng tới còi.

Cảnh báo giữ cúi không yêu cầu mắt nhắm. Cúi chủ động đủ ngưỡng cũng có thể báo; quy tắc không tự báo do giữ
nghiêng nhưng không phân biệt được mọi chuyển động chủ động.

Buzzer chỉ bật độc lập khi giữ cúi trước ≥10° đủ 0,75 giây hoặc hai mắt nhắm đủ
1,5 giây, theo nhịp 0,3 giây bật / 0,2 giây tắt. Hết dấu hiệu hợp lệ thì tắt;
không giữ còi 3 giây sau nodding và không phát còi do ngáp. Mất quan sát/gap >0,2 giây ngắt
chuỗi liên tục, không cộng thời gian mất mặt. Kết quả suy luận cũ quá 0,2 giây
không được làm mới buzzer. Firmware tự tắt sau 2 giây không nhận lệnh bật.
Hiệu chỉnh lại và thoát gửi lệnh tắt. Lỗi CDC hiển thị và được ghi báo cáo,
phần nhận diện vẫn tiếp tục, không tự kết nối lại cổng đã lỗi.

`--hardware-test` chạy 30 giây nhận video đồng thời gửi bật ở giây 1–4, tắt,
rồi bật một lần ở giây 5 và ngừng làm mới để thử watchdog. Kết quả
`transport_passed` chỉ xác nhận đọc UVC và ghi CDC thành công: firmware không
trả ACK, nên tiếng kêu và tự tắt phải được nghe/xác nhận trực tiếp.

`reports/app_*.json` lưu cấu hình, hiệu chỉnh, tốc độ và trạng thái CDC;
CSV cùng tên ghi các sự kiện và thay đổi nguy cơ. CSV `_frames.csv` lấy mẫu
5 lần/giây theo thời gian nguồn, lưu EAR, MAR/ngưỡng miệng, góc trước/sau
lọc, vận tốc pitch, thời lượng cúi, độ hợp lệ, lý do chặn chuỗi đầu và trạng
thái CDC. `alarm_active` và `alarm_reasons` là quyết định bật còi;
`observation_reasons` lưu các chuyển động/ngáp đã nhận riêng biệt. `alarm_requested` là lệnh PC muốn phát tại thời điểm lấy mẫu,
không phải xác nhận buzzer thực sự kêu. `waiting_for_rest`, `drop_too_short`,
`yaw_changed`, `yaw_out_of_range`, `cycle_timeout` và `invalid_pose` giúp
phân biệt vì sao đầu chưa được nhận. `reports/hardware_*.json`
lưu kết quả thử phần cứng. Không lưu ảnh/video. Kiểm thử video đã ghi luôn
tắt buzzer.

Quyết định nodding được ghi là `nod_alert_accepted` hoặc
`nod_alert_rejected` trong CSV sự kiện; cột `nod_alert_reason` trong CSV
đặc trưng giữ kết quả gần nhất trong 3 giây. Các lý do gồm `unknown_onset`,
`invalid_duration`, `incomplete_observation`, `frame_gap`, `invalid_pose`,
`yaw_out_of_range`, `yaw_changed` và `duplicate_event`.

Chạy kiểm thử:

```sh
.venv/bin/python -B app.py --video recording.mp4 --headless
.venv/bin/python -B -m unittest test_app test_behavior test_eye_events test_ear_windows test_windows
```

Kiểm tra trên ESP32 ngày 2026-10-13: UVC HD nhận 387 frame/30 giây
(12,94 FPS), không lỗi đọc, gửi CDC bật/tắt và thử ngừng làm mới thành công.
Luồng MediaPipe chạy đủ 30 giây, xử lý 428 frame (14,21 FPS); cửa sổ GUI
mở/đóng bình thường trong lượt 8 giây. 92 kiểm thử đạt. Hiệu chỉnh thực tế
chưa hoàn tất do đầu chuyển động; tiếng buzzer và watchdog vật lý chưa có
xác nhận trực tiếp. Các số FPS này là kết quả đo từng lượt, không phải cam kết.

Sau sửa cảnh báo đầu: 102 kiểm thử đạt, bao gồm giữ nghiêng, gục khi đầu vốn
nghiêng, hai hướng sụp bên, quay đầu lớn và luồng góc qua bộ lọc. Bản mới
chạy đủ 15 giây trên ESP32, xử lý 231 frame (15,31 FPS), CDC kết nối và không
có lỗi ứng dụng. Lượt này chưa hoàn tất hiệu chỉnh, nên chưa xác nhận các
chuỗi gục trên người thật.

Sau sửa ngáp và giữ cúi: 108 kiểm thử đạt, gồm nhận ngáp độc lập với mắt,
đếm trong lúc miệng còn mở và chống đếm trùng sau mất quan sát. Lượt GUI
45 giây hoàn tất hiệu chỉnh, CDC giữ kết nối và log camera thực tế ghi
`forward_head_drop` cùng `forward_head_bob`. CSV đặc trưng đã ghi hoạt động;
lượt này chưa có ngáp được xác nhận và chưa xác nhận trực tiếp tiếng còi.

Sau nối `nod_candidate` vào cảnh báo: 112 kiểm thử đạt, gồm trường hợp
hysteresis từng bị bộ thứ hai bỏ sót và kiểm tra lệnh CDC `ALARM 1/0` bằng
transport giả lập. Lượt GUI 30 giây hoàn tất hiệu chỉnh, xử lý 441 frame
(14,64 FPS) và giữ kết nối CDC. Lượt này không có nodding được ghi, nên
chưa xác nhận tiếng còi thực tế cho sự kiện đó.

## Mục tiêu

Hệ thống quan sát tài xế bằng camera, tổng hợp biểu hiện mắt, miệng và đầu trong cửa sổ trượt 20–30 giây để ước lượng mức buồn ngủ. Một luồng độc lập cảnh báo ngay khi quan sát được mắt nhắm kéo dài hoặc biểu hiện đầu gục đáng tin cậy.

Phiên bản đầu học trạng thái hiện tại: tỉnh táo, giảm cảnh giác, buồn ngủ. Dự đoán một sự kiện ngủ gật trong tương lai là giai đoạn riêng, cần dữ liệu có thời điểm bắt đầu sự kiện. Biểu hiện hình ảnh chưa tự xác nhận microsleep theo nhãn sinh lý EEG.

## Lộ trình

| Bước | Làm gì | Hiểu gì | Điều kiện hoàn thành |
|---|---|---|---|
| 1 — gói này | Tạo môi trường và đọc webcam | Frame, FPS, timestamp, môi trường ảo | Camera chạy ổn 30 giây và có báo cáo |
| 2 | Chạy MediaPipe Face Landmarker | Phát hiện mặt, landmarks, tracking và vùng hợp lệ | Bám được mắt/miệng/đầu, nhận biết mất quan sát |
| 3 | Nhận biết mở/nhắm và từng lần chớp | EAR, hysteresis, thời lượng theo timestamp | Chớp ngắn và nhắm dài được phân biệt |
| 4 | Nhận biết ngáp và tư thế đầu | MAR, chuỗi sự kiện, pitch/yaw/roll | Có log dấu hiệu và kiểm tra các tình huống dễ nhầm |
| 5 | Tổng hợp cửa sổ trượt | Tần suất, phân bố thời lượng, xu hướng, dữ liệu thiếu | Đặc trưng 30 giây cập nhật mỗi giây |
| 6 | Chuẩn bị dữ liệu/nhãn | Nhãn quan sát khác nhãn buồn ngủ; chia theo người | Train/val/test tách người, có kiểm tra nhãn |
| 7 | Train XGBoost baseline, sau đó GRU | Học thống kê so với học chuỗi, ablation | So sánh mắt/miệng/đầu trên cùng split |
| 8 | Tích hợp cảnh báo và đánh giá liên tục | Ngưỡng, hysteresis, báo giả/giờ, độ trễ | Báo cáo hiệu quả toàn hệ thống, không chỉ accuracy |

Các bước sau được bổ sung khi bước trước chạy ổn. Gói này chỉ triển khai bước 1.

## Chuẩn bị

- Máy CachyOS + KDE, terminal, kết nối mạng để cài công cụ và thư viện.
- Webcam tích hợp hoặc USB. Thử webcam có sẵn trước khi mua thiết bị.
- Ngồi yên, camera chắc chắn, gần ngang mặt; nhìn rõ hai mắt và miệng; ánh sáng phía trước, tránh cửa sổ sáng phía sau.
- CPU đủ để thử đọc camera. Chưa cần cấu hình CUDA, PyTorch, YOLO hay tải dataset ở bước 1.
- Chuẩn bị một tệp ghi chú cho camera, độ phân giải, ánh sáng, kính, FPS đo được và lỗi gặp phải.

## Cài công cụ hệ thống

```bash
sudo pacman -S --needed uv unzip v4l-utils
```

`uv` quản lý Python và môi trường; `unzip` giải nén; `v4l-utils` cung cấp công cụ kiểm tra webcam Linux. Nếu pacman báo lỗi mirror/404, xử lý lỗi cài gói trước khi tiếp tục; không chạy `pacman -Sy` riêng.

## Đặt dự án

Tải `driver-monitor-step01.zip`, đặt trong `~/Downloads`. Nếu trình duyệt lưu ở nơi khác, thay đường dẫn bên dưới bằng đường dẫn thực tế.

```bash
mkdir -p ~/Projects
unzip -n ~/Downloads/driver-monitor-step01.zip -d ~/Projects
cd ~/Projects/driver-monitor
```

Gói có `README.md`, `requirements.txt`, `check_camera.py`. `-n` giữ tệp đã có. Nếu thư mục `~/Projects/driver-monitor` chứa dự án khác, chọn thư mục giải nén mới để tránh trộn mã.

## Tạo môi trường Python riêng

```bash
uv python install 3.12
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python check_camera.py --check
```

Chạy lệnh trong thư mục chứa `check_camera.py`. `.venv/bin/python` chọn đúng Python của dự án; không cần activate. Sau mỗi lần mở terminal mới, `cd ~/Projects/driver-monitor` rồi tiếp tục dùng đường dẫn này. Không dùng `sudo pip`.

Chọn Python 3.12 và cố định phiên bản thư viện để giữ môi trường nhất quán. Đây là lựa chọn cho bài học, không tuyên bố là các phiên bản mới nhất. Gói `opencv-contrib-python` chứa OpenCV cùng các mô-đun bổ sung, và phù hợp với dependency của MediaPipe dự định dùng ở bước 2; mã vẫn import bằng `cv2`. OpenCV mở camera/hiển thị ảnh; NumPy biểu diễn ảnh bằng mảng số. `uv` là công cụ môi trường, không phải model AI.

Kết quả kiểm tra phải có Python 3.12.x, OpenCV 4.11.0, NumPy 2.2.6 và dòng `OK`. `--check` chỉ kiểm tra import, chưa kiểm tra phần cứng và cửa sổ.

## Kiểm tra camera

```bash
v4l2-ctl --list-devices
.venv/bin/python check_camera.py --camera 0 --seconds 30
```

Đóng ứng dụng khác đang dùng webcam trước khi chạy. Cửa sổ hiển thị ảnh và FPS vòng lặp; chạy đủ 30 giây. Q/Esc thoát sớm, Ctrl+C dừng từ terminal. Khi dừng bình thường, chương trình tạo `reports/camera_....json` và in đường dẫn.

Chương trình không lưu ảnh hay video. Báo cáo chứa phiên bản môi trường, nguồn camera, cấu hình yêu cầu, kích thước frame thực, số frame, FPS vòng lặp và khoảng cách lớn nhất giữa hai lần đọc frame thành công.

## Hiểu cách chương trình hoạt động

1. `arguments()` đọc lựa chọn dòng lệnh và kiểm tra giá trị.
2. `dependencies()` nạp OpenCV và NumPy; `environment()` in môi trường đang dùng.
3. `VideoCapture` mở camera. `set()` yêu cầu kích thước/FPS; phần cứng có thể không đáp ứng.
4. `read()` nhận một frame: mảng có dạng `(chiều cao, chiều rộng, 3 kênh BGR)`.
5. `time.perf_counter()` đo thời gian trôi qua bằng đồng hồ đơn điệu. Đây là timestamp sau khi đọc, không phải timestamp phơi sáng của cảm biến.
6. Chương trình tính FPS từ các thời điểm đọc frame, vẽ chữ và hiển thị bằng `imshow`/`waitKey`.
7. `release()` trả camera; chương trình ghi JSON để đối chiếu các lần thử.

FPS yêu cầu 30 không bảo đảm camera trả 30 frame mỗi giây. FPS vòng lặp bao gồm tốc độ đọc, xử lý và hiển thị; không tự chứng minh độ trễ từ cảnh thật tới cửa sổ. Với bước sau, mỗi thời lượng chớp/ngáp sẽ tính bằng timestamp, tránh giả định mọi frame cách nhau đúng 1/30 giây.

Ví dụ 30 giây × 30 FPS gần 900 frame, nhưng không cần đúng 900 vì có thời gian khởi động, phần cứng có thể thương lượng FPS khác và vòng lặp có độ trễ.

## Nếu có lỗi

### Camera không mở

```bash
v4l2-ctl --list-devices
.venv/bin/python check_camera.py --camera 1 --seconds 30
```

Chỉ số camera phải khớp thiết bị thực. Một webcam có thể cung cấp nhiều `/dev/video*`, trong đó không phải node nào cũng chứa ảnh. Xem định dạng của node ảnh, ví dụ:

```bash
v4l2-ctl --device=/dev/video0 --list-formats-ext
```

Không chạy chương trình bằng sudo hoặc đổi quyền toàn bộ `/dev/video*` để thử sửa lỗi. Gửi lỗi đầy đủ và danh sách thiết bị để xác định nguyên nhân.

### Lỗi Qt/Wayland khi mở cửa sổ

```bash
QT_QPA_PLATFORM=xcb .venv/bin/python check_camera.py --camera 0 --seconds 30
```

Lệnh này chỉ chọn backend Qt cho lần chạy đó và cần XWayland hoạt động. Có thể tách kiểm tra đọc camera khỏi kiểm tra cửa sổ:

```bash
.venv/bin/python check_camera.py --camera 0 --seconds 30 --headless
```

Nếu headless chạy nhưng cửa sổ lỗi, phần đọc camera và phần hiển thị đang có kết quả khác nhau. Không thay driver GPU trước khi xác định lỗi.

### FPS thấp

Thử tăng ánh sáng phía trước và xem `--list-formats-ext` để biết camera hỗ trợ độ phân giải/FPS nào. Mốc 25–30 FPS là mục tiêu thử nghiệm để quan sát chớp mắt; thấp hơn chưa tự có nghĩa chương trình sai. Ghi lại FPS và hiện tượng giật/đứng hình.

### Thư viện không import được

```bash
uv pip check --python .venv/bin/python
.venv/bin/python check_camera.py --check
```

Dùng cùng môi trường cho install và run. Không cài đồng thời các biến thể `opencv-python`, `opencv-contrib-python` và các bản `headless` trong cùng môi trường; chúng dùng chung namespace `cv2`. Bản headless không phục vụ `imshow`.

## Điều kiện hoàn thành bước 1

- `--check` thành công trong Python của dự án.
- Cửa sổ camera chạy đủ khoảng 30 giây, ảnh đủ rõ để nhìn mắt/miệng và không bị đứng hình kéo dài.
- Có báo cáo JSON; biết FPS yêu cầu, FPS camera báo và FPS vòng lặp là các thông tin khác nhau.
- Ghi lại FPS, độ phân giải thực và lỗi/hiện tượng nếu có.

Gửi output terminal, báo cáo JSON và nhận xét ảnh có mượt/rõ không. Nếu chưa chạy được, gửi nguyên lỗi ở lệnh đầu tiên bị lỗi. Bước tiếp theo là Face Landmarker, chưa phải training.

## Tài liệu gốc

- uv/Python: https://docs.astral.sh/uv/guides/install-python/
- uv/môi trường: https://docs.astral.sh/uv/pip/environments/
- OpenCV VideoCapture: https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html
- Gói OpenCV và lựa chọn GUI/headless: https://pypi.org/project/opencv-python/4.11.0.86/
- MediaPipe Face Landmarker, dùng ở bước 2: https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python
- UTA-RLDD và nhãn ba mức, dùng ở bước dữ liệu: https://sites.google.com/view/utarldd/home
- Baseline đặc trưng nhiều vùng, cửa sổ 30 giây: https://doi.org/10.3390/info16040294
