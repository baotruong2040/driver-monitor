# Bước 5 — Cửa sổ đặc trưng cho model thứ hai

Gói cập nhật cho dự án Windows đã có bước 2–4. Không cần cài thêm thư viện.
Giữ nguyên môi trường `.venv`, model MediaPipe và các tệp bước 2 (`check_face.py`,
`face_geometry.py`, `download_face_model.py`). Gói có `eye_events.py` bản fix01
không thay đổi logic đếm chớp, cùng mã bước 4 và phần bổ sung bước 5.

## 1. Ý nghĩa một dòng dữ liệu

Một dòng trong `_windows.csv` mô tả 30 giây vừa qua. Cửa sổ trượt mỗi 5 giây,
bắt đầu từ frame TRACKING đầu tiên sau hiệu chỉnh. Chỉ xuất cửa sổ đầy đủ.
Ví dụ hiệu chỉnh xong lúc 8 giây thì các khoảng gần tương ứng là [8,38), [13,43),
[18,48). Mốc thực tế tùy timestamp nguồn. Thời gian hiệu chỉnh không được dùng
để train; nhấn C tạo một đoạn mới và chờ đủ 30 giây sau hiệu chỉnh mới.

Phiên bản này tổng hợp sau khi chương trình dừng, chưa hiển thị vector cửa sổ
trực tiếp và chưa chạy model buồn ngủ/âm thanh. Cửa sổ chỉ dùng frame có timestamp
không vượt mốc kết thúc, sự kiện chỉ dùng khi đã được xác nhận trước mốc đó.

## 2. Cài và kiểm tra trong PowerShell

```powershell
Expand-Archive -Path "$env:USERPROFILE\Downloads\driver-monitor-step05.zip" -DestinationPath "$env:USERPROFILE\Documents\VSCode\AI" -Force
Set-Location "$env:USERPROFILE\Documents\VSCode\AI\driver-monitor"
.\.venv\Scripts\python.exe -m unittest -v test_behavior.py test_windows.py
.\.venv\Scripts\python.exe check_behavior.py --check
```

Dự kiến 40 tests, OK; kiểm tra model ảnh đen dự kiến faces=0.

## 3. Chạy mới với webcam hoặc MP4

```powershell
.\.venv\Scripts\python.exe check_behavior.py --camera 0 --seconds 120
.\.venv\Scripts\python.exe check_behavior.py --video ".\data\test.mp4"
```

Hiệu chỉnh vẫn cần 8 giây hợp lệ: mắt mở tự nhiên, miệng khép, nhìn thẳng.
Lệnh MP4 mặc định đọc hết video. Cúi đầu phải làm pitch dương; nếu máy bạn cần
`--pitch-sign -1`, tiếp tục dùng tham số đó. Cửa sổ mặc định 30 giây, stride 5 giây,
`--min-valid .8`, `--max-gap .2`. Có thể đặt `--window 20 --stride 5` khi cần thử.

Mỗi lần chạy tạo các tệp trong reports:

- `behavior_...._frames.csv`: từng frame, bổ sung thời gian mắt nhắm quan sát được.
- `behavior_...._events.csv`: sự kiện, bổ sung `available_at_s` là mốc xác nhận.
- `behavior_....json`: thông tin lần chạy và số cửa sổ/ số cửa sổ đạt chất lượng.
- `behavior_...._windows.csv`: vector đặc trưng, mỗi dòng một cửa sổ.
- `behavior_...._windows.json`: định nghĩa đặc trưng và tham số xuất.

Nếu đoạn TRACKING chưa đủ 30 giây, vẫn có báo cáo frame/sự kiện nhưng chưa có
windows; chương trình báo lý do rõ ràng. Không cần giảm cửa sổ chỉ để có thêm dòng.

## 4. Tổng hợp báo cáo cũ mà không chạy lại model

```powershell
.\.venv\Scripts\python.exe check_windows.py --frames ".\reports\behavior_20261011_185225_557484_frames.csv" --events ".\reports\behavior_20261011_185225_557484_events.csv" --output ".\reports\behavior_20261011_185225_557484_step05_windows.csv"
```

Cần cả frames và events của cùng một lần chạy. Exporter không ghi đè tệp đầu ra:
nếu đã tồn tại, đổi tên `--output`. Báo cáo cũ chưa có `available_at_s`, nên tạm dùng
`end_s` và ghi metadata `legacy_end_s_approximation`. Một số sự kiện mắt được xác
nhận sau end_s một vài frame; muốn đánh giá sát thời điểm online, chạy lại video
bằng mã mới. Tổng hợp CSV cũ không sửa các cờ/sự kiện đã ghi trong bước 4.

## 5. Công thức và cột cần đọc

| Cột | Ý nghĩa |
|---|---|
| window_start_s, window_end_s | Giới hạn thời gian nguồn, khoảng [start,end) |
| eyes_valid_s, mouth_valid_s, head_valid_s | Tổng thời gian hợp lệ riêng từng kênh |
| *_valid_ratio | Thời gian hợp lệ / 30 giây |
| eyes_closed_s | Thời gian quan sát hai mắt CLOSED |
| eyes_closed_ratio | eyes_closed_s / eyes_valid_s |
| blink_candidate_count | Số chớp ứng viên được xác nhận trong cửa sổ |
| blink_candidate_per_valid_min | Số chớp × 60 / thời gian mắt hợp lệ |
| completed_eye_duration_mean_s, completed_eye_duration_max_s | Thời lượng của các lần nhắm hoàn tất được xác nhận trong cửa sổ, biết mốc bắt đầu |
| longest_observed_closed_s | Đoạn CLOSED liên tục dài nhất quan sát được bên trong cửa sổ |
| yawn_candidate_count | Số ngáp ứng viên được xác nhận trong cửa sổ |
| mouth_open_s, mouth_open_ratio | Thời gian và tỷ lệ miệng mở lớn |
| nod_candidate_count | Số cúi–trở lại ứng viên được xác nhận |
| head_down_s, head_down_ratio | Thời gian và tỷ lệ đầu cúi |
| pitch_mean_deg, pitch_std_deg | Trung bình và độ lệch chuẩn pitch, có trọng số thời gian |
| eyes_closed_mouth_open_s | Thời gian đồng thời mắt nhắm và miệng mở lớn |
| eyes_closed_without_mouth_open_s | Thời gian mắt nhắm khi miệng được xác nhận CLOSED |
| joint_eyes_mouth_valid_s | Thời gian cả mắt và miệng hợp lệ |
| *_usable, all_channels_usable | 1 nếu đủ chất lượng theo ngưỡng, 0 nếu thiếu |
| subject_id, video_id, label | Để trống, sẽ bổ sung bằng nhãn thật trước khi train |

Ví dụ trong cửa sổ 30 giây có 24 giây mắt hợp lệ và 6 giây CLOSED:
`eyes_valid_ratio = 24/30 = .8`, `eyes_closed_ratio = 6/24 = .25`.
Không dùng 6/30, vì 6 giây còn lại chưa biết mắt mở hay nhắm.

Tỷ lệ CLOSED này là tỷ lệ dựa trên ngưỡng EAR của dự án, chưa phải PERCLOS được
định nghĩa theo mức khép mí 80%. Giá trị không có mẫu số hợp lệ để trống, không
điền 0. Khi đọc để train, phải xử lý missing values trong pipeline học từ tập train.

Một khoảng giữa hai frame chỉ được tính nếu cả hai đầu hợp lệ và khoảng cách
không vượt max-gap. CLOSED/OPEN/DOWN chỉ được tính khi hai đầu cùng trạng thái.
Khoảng chuyển trạng thái vẫn có thể là thời gian kênh hợp lệ, nhưng không khẳng
định trạng thái hoạt động; phép đo vì vậy bảo thủ khoảng một frame tại mỗi biên.
Frame sau window_end không được dùng; phần đuôi chưa có hai đầu quan sát là unknown.
Không kéo dài frame cuối, không nối qua mất mặt và không nối qua hiệu chỉnh.

Sự kiện được đếm theo mốc xác nhận trong [start,end). Một sự kiện có thể bắt đầu
trước cửa sổ, nhưng hoàn tất trong cửa sổ: cột duration của sự kiện hoàn tất mô tả
cả sự kiện đó. Ngược lại, cột longest_observed_closed_s chỉ đo phần nằm bên trong.
Cờ mouth_held_flag/head_held_flag/long_closure_flag không được đếm thêm thành ngáp,
gật hoặc chớp. Một sự kiện có thể xuất hiện ở nhiều cửa sổ chồng lấn — đó là dữ
liệu cho các thời điểm đánh giá khác nhau, không phải tổng sự kiện của cả video.

## 6. Khi ngáp cũng nhắm mắt lâu

Giữ dữ liệu cả mắt và miệng. Bổ sung thời gian trùng `eyes_closed_mouth_open_s`;
không tự xóa đoạn nhắm mắt khi miệng mở. Mở miệng lớn cũng có thể là nói hoặc
hành động có chủ ý, nên cột trùng chưa chứng minh ngáp. Trong dữ liệu có nhãn,
ghi riêng thao tác/ngữ cảnh và trạng thái buồn ngủ; đừng gán label drowsy chỉ vì
mã phát hiện yawn_candidate. Model thứ hai sẽ học sự phối hợp tín hiệu khi có
nhãn đủ tốt. Bài thử mô phỏng dùng xác nhận chức năng, chưa chứng minh buồn ngủ.

## 7. Lấy lại quan sát khi mắt đã nhắm

Máy đếm chớp vẫn cần mốc OPEN → CLOSED → OPEN. Nhánh quan sát mới đo từ frame
CLOSED đầu tiên lấy lại được; `eye_observed_closed_s` là thời lượng tối thiểu
đã quan sát. `eye_observed_start_known=0` cho biết không biết mốc bắt đầu thật.
Sau 1.5 giây CLOSED liên tục, `long_closure=1` và ghi một
`observed_long_closure_flag` với `start_known=0`. Nó không được tính thành chớp.
Mất mặt, hai mắt bất đồng hoặc khoảng frame > .2 giây làm nhánh này bắt đầu lại.
Đây là cờ quan sát, chưa phát âm thanh và chưa kết luận buồn ngủ.

## 8. Bài thử và chuẩn bị nhãn

Sau hiệu chỉnh, quay 120 giây: nhìn thẳng, chớp, mô phỏng ngáp kèm nhắm mắt,
cúi–trở lại, cúi giữ và che mặt. Thêm bài thử mắt mở → che mặt → bỏ tay khi còn
nhắm khoảng 2 giây → mở. Kiểm tra thời lượng mới bắt đầu từ lúc mặt trở lại,
cờ xuất hiện sau 1.5 giây quan sát, không cộng thời gian che.

Gửi frames/events, JSON lần chạy và windows CSV kèm mốc thao tác.
Cửa sổ chất lượng thấp được giữ để kiểm tra; mặc định chỉ chọn
all_channels_usable=1 cho baseline model dùng đủ ba kênh. Đây là bộ lọc dữ liệu,
không phải nhãn tỉnh táo hoặc buồn ngủ.

Trước khi train: gán subject_id/video_id, xác định quy tắc label theo mốc thời
gian và nhãn nguồn/thẩm định. Chia train/validation/test theo người; giữ các video
của cùng người trong cùng tập. Chia trước khi tạo cửa sổ; không chia ngẫu nhiên
các cửa sổ chồng lấn vì chúng chứa nhiều frame trùng và gây rò rỉ dữ liệu.
Không cần dùng mọi cột CSV làm input: IDs/mốc thời gian/label/usable dùng quản lý
và lọc, không phải đặc trưng hành vi. Chưa huấn luyện model trong bước này.

## 9. Kiểm chứng đã thực hiện

- 40 bài logic cho bước 4–5, gồm thời gian nguồn, mất mặt, khoảng frame, cửa sổ,
  mẫu số 0, ngáp–nhắm mắt trùng nhau, causal availability và không đếm đôi cờ.
- Kiểm tra tích hợp Processor: mắt nhắm với mốc đầu không biết tạo cờ quan sát,
  mở lại không tạo blink_candidate.
- Tổng hợp báo cáo behavior_20261011_185225_557484: 17 cửa sổ 30 giây/stride 5 giây,
  11 cửa sổ đủ chất lượng cả ba kênh tại ngưỡng .8; 6 cửa sổ chưa đủ.
- Model thật/webcam Windows và cờ mới cần xác nhận trên máy bạn.
