# Bước 4 — Miệng, ngáp ứng viên và tư thế đầu

## Mục tiêu

Ta đã có EAR và sự kiện mắt ở bước 3. Bước 4 bổ sung hai nguồn thông tin:

1. Độ mở miệng và thời lượng một lần mở miệng lớn.
2. Pitch/yaw/roll của đầu so với tư thế trung tính, tốc độ pitch và sự kiện cúi–trở lại.

Chương trình mới vẫn ghi mắt để có thể so sánh các tín hiệu trên cùng timestamp.
Chưa có model đánh giá buồn ngủ, cửa sổ tổng hợp 30 giây hoặc âm thanh.

## Chuẩn bị và tệp

Giữ .venv Python 3.12, model và dependency bước 2. Cần eye_events.py đã cập nhật
ở bản sửa bước 3. Không cần cài thư viện mới, tải model khác hoặc cấu hình CUDA.

| Tệp bổ sung | Công dụng |
| --- | --- |
| behavior_features.py | MAR_simple, rotation, lọc góc và máy trạng thái miệng/đầu |
| check_behavior.py | Pipeline mới gồm mắt + miệng + đầu, webcam hoặc video |
| test_behavior.py | 21 bài kiểm tra logic không cần webcam/model |
| README-step04.md | Hướng dẫn này |

Mã dùng lại eye_events.py, face_geometry.py, check_face.py và download_face_model.py.
check_eyes.py của bạn vẫn có thể chạy riêng như bước 3. ZIP không thay các tệp cũ.

## Cài và kiểm tra trong PowerShell

Tải driver-monitor-step04.zip vào Downloads, giải nén vào thư mục AI:

```powershell
Expand-Archive -Path "$env:USERPROFILE\Downloads\driver-monitor-step04.zip" -DestinationPath "$env:USERPROFILE\Documents\VSCode\AI" -Force
Set-Location "$env:USERPROFILE\Documents\VSCode\AI\driver-monitor"
.\.venv\Scripts\python.exe -m unittest -v test_behavior.py
.\.venv\Scripts\python.exe check_behavior.py --check
```

Test dự kiến: Ran 21 tests và OK. Model chạy trên ảnh đen dự kiến faces=0.
Đây chưa phải kiểm tra độ chính xác góc đầu hoặc miệng.

Chạy webcam:

```powershell
.\.venv\Scripts\python.exe check_behavior.py --camera 0 --seconds 120
```

Chạy MP4 trực tiếp, đến hết tệp:

```powershell
.\.venv\Scripts\python.exe check_behavior.py --video ".\data\test.mp4"
```

Không thêm --seconds nếu muốn xử lý hết video. Khi có --seconds, nó giới hạn
thời gian nguồn video, không phải thời gian thực để máy xử lý. Video có thể
được xử lý nhanh hơn tốc độ phát. Muốn kiểm tra không mở cửa sổ, thêm --headless.

## Hiệu chỉnh đầu tiên

Trong 8 giây quan sát hợp lệ đầu:

- Nhìn thẳng, để cả mặt nằm trong khung.
- Mắt mở tự nhiên, miệng khép nhẹ; có thể chớp bình thường.
- Giữ đầu trung tính, không nói, không ngáp, không quay đầu.

Mã lấy EAR mắt mở theo phân vị 70 như bước 3, mức miệng khép theo phân vị 30,
và ma trận rotation trung bình làm tư thế tham chiếu.
Khoảng mất quan sát không được cộng vào thời gian hiệu chỉnh.
Nếu đầu chuyển động quá nhiều (phân vị 90 của độ lệch góc vượt 8 độ), mã dừng
và yêu cầu chạy lại với đầu giữ thẳng. Kiểm tra này không tự xác nhận miệng
khép hay mắt mở, nên bạn vẫn phải thực hiện đúng hướng dẫn.

Nhấn C để hiệu chỉnh lại, Q/Esc để thoát. Khi hiệu chỉnh lại, sự kiện đang đo
bị ngắt; bộ đếm của toàn lần chạy và lịch sử các lần hiệu chỉnh hoàn tất được giữ.
Hiệu chỉnh riêng cho mỗi người/camera/video. Không hiệu chỉnh bằng mặt thật
rồi đưa màn hình điện thoại có người khác vào.

## 1. Độ mở miệng: MAR_simple

Mã tính trên tọa độ pixel:

MAR_simple = distance(landmark 13, landmark 14) / distance(landmark 78, landmark 308).

13 và 14 nằm ở môi trong trên/dưới; 78 và 308 là hai khóe của đường môi trong.
Khoảng môi được chuẩn hóa bằng chiều rộng miệng. Ví dụ khoảng môi 24 px,
chiều rộng 60 px → MAR_simple = 0,40.

Đây là định nghĩa đơn giản của dự án, không phải mọi công thức MAR trong các
bài báo. Nó không chứng minh một người ngáp. Nói, hát, cười hoặc giữ miệng mở
đều có thể làm nó tăng. Thời lượng giúp tách một số mở miệng ngắn, nhưng không
đủ để phân biệt chắc chắn ngáp với nói.

Ngưỡng sau hiệu chỉnh:

- Mở: max(0,45; mức miệng khép + 0,25).
- Khép lại: max(0,30; mức miệng khép + 0,15).

Hai ngưỡng tạo hysteresis. Giá trị ở giữa giữ trạng thái trước.
Thông số là lựa chọn thử nghiệm của dự án, chưa được huấn luyện từ dataset.

| Bản ghi miệng | Ý nghĩa |
| --- | --- |
| mouth_open_event | Một chuỗi mở–khép ngoài khoảng thời lượng ngáp ứng viên |
| yawn_candidate | Chuỗi mở lớn rồi khép, dài 1,5–10 giây, có mốc bắt đầu đã biết |
| mouth_held_flag | Quan sát mở lớn liên tục đủ 1,5 giây; ghi ngay khi đang mở |
| observed_mouth_segment | Đoạn mở sau khi lấy lại quan sát, không biết mốc thật bắt đầu |
| interrupted_mouth | Sự kiện bị ngắt bởi mất dữ liệu, góc không phù hợp, hiệu chỉnh hoặc kết thúc |

Flag và completed event có thể thuộc cùng một lần mở. Không cộng chúng như
hai lần ngáp. Không tự đổi yawn_candidate thành nhãn yawn trong dữ liệu train.

## 2. Góc đầu: pitch, yaw, roll

| Góc | Chuyển động cần thử |
| --- | --- |
| Pitch | Cúi xuống / ngẩng lên |
| Yaw | Quay trái / phải |
| Roll | Nghiêng đầu về vai trái / phải |

Face Landmarker có tùy chọn xuất ma trận biến đổi khuôn mặt. Ta bật tùy chọn
đó ở chương trình bước 4. Khối 3 × 3 của ma trận được xử lý SVD để lấy rotation
gần nhất, tách ảnh hưởng scale. Ma trận thiếu, không hữu hạn, reflection hoặc
co giãn bất thường bị từ chối. Đây là kiểm tra số học, không bảo đảm model
đã quan sát đúng mặt.

Ta không trừ trực tiếp Euler angles của hai frame. Mã dùng rotation tương đối:

R_relative = R_current × transpose(R_neutral).

Sau đó lấy Euler theo quy ước Rz(roll) × Ry(yaw) × Rx(pitch).
Góc hiển thị là thay đổi so với tư thế trung tính của bạn trong hệ trục camera.
Đây là ước lượng từ model khuôn mặt, không phải phép đo góc tuyệt đối từ camera
đã hiệu chuẩn. Các góc Euler còn phụ thuộc quy ước, nhất là khi đầu quay nhiều.

Điểm cần xác nhận trên máy bạn: nhìn thẳng rồi cúi xuống. Mặc định mong muốn
pitch dương khi cúi xuống. Nếu ngược, chạy:

```powershell
.\.venv\Scripts\python.exe check_behavior.py --camera 0 --seconds 120 --pitch-sign -1
```

Đừng đổi dấu dựa vào trái/phải của hình ảnh. Hãy dựa vào thao tác cúi thật.
Yaw/roll ghi dấu theo phép phân rã; bài thử xác định hướng tương ứng trên camera.

Mã lọc góc bằng exponential smoothing với hằng số thời gian 0,15 giây, dùng
delta timestamp thực. Bộ lọc giảm rung nhưng gây trễ; mốc sự kiện đầu là mốc
góc đã lọc vượt ngưỡng. CSV có cả góc chưa lọc và góc đã lọc để kiểm tra.
Tốc độ pitch là chênh góc đã lọc / delta thời gian, đơn vị độ/giây.
Sau mất dữ liệu/gián đoạn lớn, bộ lọc reset và không đo tốc độ xuyên qua khoảng trống.

## 3. Cúi và gật đầu ứng viên

Trạng thái DOWN bắt đầu khi pitch đã lọc ≥ 15 độ. Trở về NEUTRAL khi pitch
≤ 8 độ. Trong khoảng 8–15 độ, giữ trạng thái trước. NEUTRAL ở đây nghĩa là
đã rời trạng thái cúi xuống; ngẩng lên cũng có thể là NEUTRAL theo detector này.

| Bản ghi đầu | Ý nghĩa |
| --- | --- |
| nod_candidate | Đã thấy NEUTRAL → DOWN → trở lại, dài 0,2–2,5 giây |
| head_down_event | Chuỗi cúi–trở lại ngoài khoảng thời lượng nod_candidate |
| head_held_flag | Quan sát DOWN liên tục đủ 2 giây |
| observed_head_segment | Đoạn DOWN chưa biết mốc bắt đầu |
| interrupted_head | Ngắt do mất dữ liệu, góc quá lớn, hiệu chỉnh hoặc kết thúc |

Nod candidate được ghi khi trở lại, không phải chỉ vì đầu đang cúi.
Nhìn bảng điều khiển hoặc cúi có chủ đích vẫn có thể tạo cùng sự kiện. Bộ này
chưa kết luận gật do buồn ngủ, chưa học động học head bobbing.
Khoảng 2–2,5 giây có thể vừa có held flag vừa hoàn tất nod candidate theo cấu
hình mặc định; đó vẫn là một sự kiện, hai bản ghi khác thời điểm.

## 4. Chất lượng và thiếu quan sát

Mắt, miệng, đầu có trạng thái hợp lệ riêng. Ví dụ vùng miệng không hợp lệ
không tự làm mất dữ liệu mắt. Đầu chỉ hợp lệ khi có ma trận, head landmarks
đạt kiểm tra và các góc tương đối có độ lớn ≤ 60 độ.

Miệng yêu cầu thêm góc chưa lọc trong giới hạn:

- abs(pitch) ≤ 35 độ;
- abs(yaw) ≤ 45 độ;
- abs(roll) ≤ 35 độ.

Đây là giới hạn thử nghiệm để giảm méo tỷ lệ miệng khi mặt quay lớn. Khi qua
giới hạn, mã ngắt miệng ngay thay vì nối sự kiện qua đoạn khó quan sát. Điều
này có thể bỏ sót một lần ngáp khi đầu nghiêng nhiều; cần đánh giá sau này.

Mất mặt hoặc một vùng không hợp lệ → UNKNOWN cho kênh liên quan, không
ghi giá trị thiếu thành 0. Khoảng source timestamp > 0,20 giây ngắt sự kiện.
Landmarks có thể vẫn được model suy đoán dưới vật che, nên các kiểm tra hình
học và ma trận không phát hiện chắc chắn mọi che khuất.

Nếu lấy lại mặt khi miệng đã mở hoặc đầu đã cúi, mã ghi start_known=0.
Thời lượng lúc đó là đoạn quan sát được, một giới hạn dưới; held flag vẫn có
thể xuất hiện sau đủ thời gian quan sát, nhưng không tạo complete yawn/nod
candidate nếu thiếu mốc bắt đầu. Mắt tiếp tục dùng logic bước 3: muốn đo một
sự kiện mắt hoàn chỉnh cần thấy OPEN trước CLOSED. Luồng cảnh báo khẩn cho
trường hợp bắt đầu quan sát với mắt đã nhắm vẫn cần bổ sung trước tích hợp cuối.

## 5. Bài thử 120 giây

Giữ camera cố định, ánh sáng phía trước, đủ thấy mắt và miệng. Thực hiện tại bàn.
Sau hiệu chỉnh, thử từng nhóm và chừa khoảng 3 giây nhìn thẳng/miệng khép giữa
các thao tác để các bộ lọc và máy trạng thái trở lại mức trung tính.

| Thao tác | Kết quả quan sát mong muốn |
| --- | --- |
| Giữ miệng khép 10 giây | CLOSED ổn định, không tăng yawn_candidate |
| Nói bình thường 10 giây | MAR thay đổi; kiểm tra có ứng viên giả hay không |
| Mở miệng lớn khoảng 0,5 giây rồi khép, 2 lần | mouth_open_event, thường chưa đạt thời lượng ngáp |
| Mô phỏng ngáp mở lớn 2–3 giây rồi khép, 2 lần | held flag lúc mở, yawn_candidate khi khép nếu ngưỡng đạt |
| Cúi nhẹ rồi trở lại, 3 lần | Pitch tăng đúng dấu; nod_candidate nếu đạt biên độ/thời lượng |
| Cúi giữ khoảng 3 giây rồi trở lại | held flag; có thể head_down_event khi trở lại |
| Quay trái/phải, rồi nghiêng về vai | Yaw/roll thay đổi; quan sát chất lượng của từng vùng |
| Che mặt 3 giây rồi bỏ tay | UNKNOWN; không cộng đoạn che vào sự kiện |
| Chớp vài lần, mở miệng/cúi lại một lần | Các kênh phục hồi sau mất quan sát |

Đừng cố tạo biểu hiện buồn ngủ; đây là bài thử cơ chế đo.
Nói kéo dài một nguyên âm hoặc giữ miệng mở có thể bị ghi yawn_candidate:
hãy ghi rõ thao tác để ta đánh giá false positives, không coi đó là model đã
phân biệt ngáp/nói. Video test.mp4 cũ chủ yếu kiểm tra mắt/che mặt; cần quay
thêm đoạn có miệng và chuyển động đầu theo bài thử này.

Nếu dùng MP4, 8 giây đầu cần nhìn thẳng, miệng khép. Không cắt bắt đầu video
ngay lúc ngáp/cúi. Chạy trực tiếp MP4, không quay lại màn hình điện thoại.

## 6. Báo cáo và cách đọc

Trong reports/, mỗi lần chạy có:

- behavior_....json: môi trường, nguồn, nguyên nhân dừng, FPS xử lý, số frame,
  cấu hình/ngưỡng, baseline và bộ đếm sự kiện.
- behavior_...._frames.csv: EAR, MAR_simple, trạng thái từng kênh, góc raw/filtered,
  vận tốc pitch, thời lượng đang đo, cờ, lý do chất lượng và timestamp nguồn.
- behavior_...._events.csv: channel, kind, start_s, end_s, duration_s, start_known,
  peak và lý do kết thúc/ngắt.

peak của miệng là MAR_simple lớn nhất; peak của đầu là pitch đã lọc lớn nhất.
Các bản ghi mắt không có peak nên cột đó trống. start_known=1 của bản ghi mắt
cho biết logic đó bắt đầu từ OPEN; start_known=0 của miệng/đầu là đoạn quan sát
thiếu mốc bắt đầu. Một flag và một completed event có thể cùng start_s.

Số frame và source_fps của video khác processing_fps. Thời lượng sự kiện theo
video, dù CPU chạy nhanh/chậm. Khi CAP_PROP_POS_MSEC không tăng hợp lệ, mã
dùng 1/source_fps để dự phòng và ghi timestamp_fallbacks. Fallback giả định
FPS cố định, nên không dùng nó để tuyên bố độ chính xác thời gian trên video
FPS biến thiên. Nếu đọc dừng trước frame count trong metadata, báo lỗi; frame
count có thể không chính xác trên một số tệp. Không có frame count, trạng thái
dừng ghi rõ video_end_or_decode_failure vì OpenCV không phân biệt hai trường hợp.

Chương trình không lưu ảnh hoặc video. Hãy gửi ba báo cáo cùng video bài thử
nếu muốn đối chiếu thao tác với timestamp.

## 7. Xử lý lỗi và điều chỉnh

| Vấn đề | Việc cần làm |
| --- | --- |
| Import thiếu eye_events/face_geometry/check_face | Giải nén vào cùng driver-monitor, giữ mã bước 2–3 |
| CALIBRATING không kết thúc | Kiểm tra cả mặt, miệng và matrix hợp lệ; giữ đầu ổn định |
| Cúi xuống làm pitch âm | Chạy lại với --pitch-sign -1 |
| Miệng mở lớn mà không OPEN | Quan sát MAR và mouth_reason trước khi đổi ngưỡng |
| Quay đầu khiến miệng UNKNOWN | Kiểm tra pose gate; đây có thể là ngắt chất lượng dự kiến |
| Nói chuyện tạo yawn_candidate | Ghi video/nhãn; baseline chưa phân biệt chắc chắn nói/ngáp |
| Đầu trở lại nhưng sự kiện chưa kết thúc | Chờ pitch đã lọc về ≤ nod-exit; lọc có trễ |

Ví dụ điều chỉnh sau khi đã xem số đo:

```powershell
.\.venv\Scripts\python.exe check_behavior.py --camera 0 --seconds 120 --mouth-open 0.40 --mouth-close 0.25
```

Đây là ngưỡng tối thiểu: ngưỡng thật vẫn lấy max với baseline + offset.
Chỉ đổi từng nhóm tham số và lưu báo cáo để so sánh. --help liệt kê các lựa chọn.

## 8. Đọc mã và tiêu chí hoàn thành

Đọc behavior_features.py theo thứ tự mouth_ratio → rotation_from_matrix →
relative_angles → AngleFilter → DurationTracker. Sau đó đọc Processor.update()
và run() trong check_behavior.py. Mỗi lớp xử lý một việc để bạn có thể hiểu,
thử riêng và thay phương pháp sau này.

Hoàn thành baseline bước 4 khi:

- Nạp model và hiệu chỉnh thành công.
- MAR tăng khi mở miệng, giảm khi khép.
- Pitch/yaw/roll phản ứng với chuyển động đúng trục, pitch cúi đúng dấu.
- Ngáp mô phỏng/cúi–trở lại tạo sự kiện có thời gian hợp lý.
- Nói và quay đầu được kiểm tra để ghi nhận hạn chế/ứng viên giả.
- Che mặt ngắt dữ liệu và các kênh phục hồi sau đó.

Bước 5 sẽ tổng hợp mắt–miệng–đầu cùng chất lượng trên cửa sổ 30 giây.
Chưa dùng các event heuristic làm nhãn drowsiness để train.

## Cơ sở kỹ thuật và kiểm tra gói

Tài liệu chính thức về ma trận Face Landmarker:
https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/FaceLandmarkerOptions

Ma trận được Google mô tả để biến đổi mặt chuẩn sang mặt phát hiện. Phép SVD,
góc tương đối, MAR_simple, ngưỡng, pose gates và máy trạng thái trong gói này
là thiết kế thử nghiệm của dự án, không phải thuật toán nhận diện ngáp/gật
được Google cung cấp sẵn.

21 bài kiểm tra logic đã qua. Luồng video giả lập đã kiểm tra EAR/chớp, ngáp
ứng viên, gật ứng viên, cúi giữ, mất mặt, timestamp nguồn độc lập thời gian xử
lý và ghi CSV/JSON. Môi trường xây gói không có MediaPipe/webcam Windows để
chạy model thật; lệnh --check và bài thử camera/video trên máy bạn là xác nhận
còn lại, đặc biệt cho dấu pitch và ngưỡng miệng.
