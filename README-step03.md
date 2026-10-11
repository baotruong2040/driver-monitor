# Bước 3 — EAR và sự kiện chớp/nhắm mắt (Windows)

## 1. Mục tiêu và phạm vi

Sau bước 2, webcam của bạn chạy khoảng 30 FPS và Face Landmarker lấy lại mặt sau khi bỏ vật che. Bước này chuyển tọa độ landmarks thành tín hiệu mắt và các sự kiện có thời gian.

Bạn sẽ hiểu và kiểm tra được:

- EAR được tính từ sáu điểm quanh mỗi mắt.
- Hai ngưỡng đóng/mở giúp trạng thái ổn định hơn.
- Một lần chớp là một chuỗi mở → nhắm → mở, không phải một frame EAR thấp.
- Thời lượng được đo bằng timestamp, không bằng số frame / 30.
- Che mặt, một mắt không hợp lệ và khoảng gián đoạn lớn sẽ ngắt sự kiện.

Đây là baseline hình học để thu thập dữ liệu, chưa có model đánh giá buồn ngủ, PERCLOS hay âm thanh. Cờ LONG CLOSURE chỉ nói rằng hệ thống quan sát hai mắt đóng đủ lâu theo tham số thử nghiệm.

## 2. Tệp và điều kiện có sẵn

ZIP chỉ thêm bốn tệp vào `driver-monitor`:

| Tệp | Vai trò |
| --- | --- |
| `eye_events.py` | Công thức EAR và máy trạng thái độc lập với camera |
| `check_eyes.py` | Camera → landmarks → EAR → sự kiện → CSV/JSON |
| `test_eye_events.py` | 14 bài kiểm tra logic, không cần webcam |
| `README-step03.md` | Hướng dẫn này |

Chương trình dùng lại `check_face.py`, `face_geometry.py`, `download_face_model.py` và `models/face_landmarker.task` của bước 2. Tiếp tục dùng môi trường `.venv` với Python 3.12 đã chạy thành công. Không cần cài thư viện mới.

## 3. Giải nén và kiểm tra trong PowerShell

Tải ZIP vào Downloads. Đóng chương trình webcam đang chạy. Mở PowerShell và thực hiện:

```powershell
Expand-Archive -Path "$env:USERPROFILE\Downloads\driver-monitor-step03.zip" -DestinationPath "$env:USERPROFILE\Documents\VSCode\AI" -Force
Set-Location "$env:USERPROFILE\Documents\VSCode\AI\driver-monitor"
```

Đổi đường dẫn nếu bạn lưu ZIP hoặc dự án ở vị trí khác. ZIP có thư mục gốc `driver-monitor`, nên đích giải nén là thư mục **AI**, không phải thư mục driver-monitor bên trong.

Kiểm tra logic:

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_eye_events.py
```

Kết quả dự kiến: `Ran 14 tests` rồi `OK`. Các bài kiểm tra xác nhận thời lượng theo timestamp, hysteresis, che mặt, gián đoạn frame, nháy một mắt, tín hiệu không hữu hạn và đóng mắt ngay khi bắt đầu quan sát.

Kiểm tra nạp model:

```powershell
.\.venv\Scripts\python.exe check_eyes.py --check
```

Kết quả dự kiến: model chạy trên ảnh đen, `faces=0`. Điều này chưa kiểm tra độ chính xác mắt.

Không cần kích hoạt môi trường hoặc đổi ExecutionPolicy vì ta gọi trực tiếp interpreter trong `.venv`. Trên Windows cũng không cần biến `QT_QPA_PLATFORM=xcb` của Linux.

## 4. EAR: từ tọa độ đến độ mở tương đối

Sáu điểm được sắp theo đường bao mắt:

- p1 và p4: hai khóe mắt.
- p2/p6 và p3/p5: hai cặp điểm mí trên–mí dưới.

EAR = (distance(p2,p6) + distance(p3,p5)) / (2 × distance(p1,p4)).

Tử số đo hai khoảng mí. Mẫu số chuẩn hóa bằng chiều rộng mắt. Khi mắt đóng, khoảng mí giảm nên EAR thường giảm. EAR không phải phần trăm đồng tử bị che và không trực tiếp xác nhận trạng thái sinh lý ngủ.

Ví dụ: hai khoảng mí đều 6 pixel, chiều rộng mắt 30 pixel → EAR = 12/60 = 0,20. Nếu cùng các điểm được phóng to gấp đôi, EAR không đổi. Tuy vậy quay đầu, kính, góc camera và sai số landmarks vẫn có thể làm EAR thay đổi.

MediaPipe cung cấp x/y chuẩn hóa theo chiều rộng/chiều cao ảnh. Với ảnh 640 × 480, dùng trực tiếp các tọa độ chuẩn hóa trong công thức khoảng cách sẽ làm sai tỷ lệ trục. Mã dùng tọa độ pixel của `inspect_face()` để hai trục có cùng đơn vị.

Các chỉ số dùng lại từ bước 2:

| Mắt theo quy ước landmarks | p1, p2, p3, p4, p5, p6 |
| --- | --- |
| Trái | 362, 385, 387, 263, 373, 380 |
| Phải | 33, 160, 158, 133, 153, 144 |

L/R là theo quy ước model, không nhất thiết tương ứng bên trái/phải màn hình. Ta chưa lật ảnh trước khi suy luận.

## 5. Hiệu chỉnh mức mắt mở

Chạy lần đầu:

```powershell
.\.venv\Scripts\python.exe check_eyes.py --camera 0 --seconds 90
```

Trong pha `CALIBRATING`, nhìn thẳng, giữ mắt mở tự nhiên và ánh sáng ổn định. Bạn có thể chớp bình thường, nhưng chưa thực hiện bài thử nhắm lâu hoặc che mặt.

Mã tích lũy ít nhất **8 giây hai mắt hợp lệ** và ít nhất 60 mẫu. Khoảng mất quan sát và khoảng cách frame lớn hơn 200 ms không được cộng vào thời gian hiệu chỉnh. Vì vậy pha này có thể kéo dài hơn 8 giây thời gian thực.

Mức EAR mắt mở được lấy bằng phân vị 70 của mẫu, riêng cho từng mắt. Cách chọn này giảm ảnh hưởng của vài lần chớp ngắn, nhưng không bảo đảm hiệu chỉnh đúng nếu bạn nhắm mắt phần lớn thời gian hoặc landmarks sai. Hãy xem trực tiếp trạng thái sau khi hiệu chỉnh.

Ngưỡng mặc định:

- đóng = 0,65 × mức EAR mắt mở;
- mở lại = 0,80 × mức EAR mắt mở.

Ví dụ mức mắt mở 0,30 → ngưỡng đóng 0,195 và ngưỡng mở 0,240. Hai hệ số là lựa chọn kỹ thuật ban đầu của dự án, cần điều chỉnh/đánh giá bằng dữ liệu; không phải ngưỡng lấy từ nghiên cứu để chẩn đoán buồn ngủ.

Nhấn **C** để hiệu chỉnh lại sau khi thay đổi vị trí camera hoặc khi trạng thái sai rõ ràng. Sự kiện đang đo bị ngắt. Bộ đếm sự kiện của toàn lần chạy vẫn giữ nguyên; JSON lưu lịch sử các lần hiệu chỉnh hoàn tất.

## 6. Máy trạng thái và hysteresis

Mỗi mắt được xử lý riêng:

| Điều kiện | Trạng thái |
| --- | --- |
| EAR ≤ ngưỡng đóng | CLOSED |
| EAR ≥ ngưỡng mở | OPEN |
| EAR nằm giữa hai ngưỡng | Giữ trạng thái trước đó |
| Chưa biết trạng thái, EAR ở vùng giữa | UNKNOWN |

Đây là hysteresis: cần một ngưỡng để chuyển sang nhắm và ngưỡng cao hơn để mở lại. Nó giảm việc trạng thái nhảy liên tục khi EAR dao động gần ngưỡng, nhưng không loại bỏ mọi nhiễu.

Hai mắt cùng OPEN → trạng thái chung OPEN. Hai mắt cùng CLOSED → CLOSED. Mất mặt, một mắt không đạt kiểm tra, hoặc hai mắt bất đồng → UNKNOWN và ngắt sự kiện đang đo. Nháy một mắt không được đếm thành chớp hai mắt ở baseline này.

Chỉ cần vùng hai mắt hợp lệ để tính EAR. Miệng không hợp lệ không tự làm mất dữ liệu mắt. Các kiểm tra hình học vẫn không nhận biết chắc chắn mọi trường hợp che khuất: MediaPipe có thể suy đoán landmarks dưới bàn tay hoặc kính. Kiểm tra che mặt trên hình ảnh thực là cần thiết.

## 7. Sự kiện và thời lượng

Mốc bắt đầu là frame quan sát chuyển OPEN → CLOSED. Mốc kết thúc là frame quan sát CLOSED → OPEN. Hiệu hai timestamp là thời lượng ước tính. Mốc thật có thể nằm giữa hai frame; không thể suy ra độ chính xác mili giây chỉ vì timestamp có nhiều chữ số.

| Loại sự kiện | Quy tắc thử nghiệm mặc định |
| --- | --- |
| `brief_closure` | Chuỗi đóng–mở ngắn hơn 0,06 giây |
| `blink_candidate` | Chuỗi đóng–mở từ 0,06 đến 0,50 giây |
| `prolonged_closure` | Chuỗi đóng–mở dài hơn 0,50 giây |
| `long_closure_flag` | Phát một lần khi sự kiện đang đo đạt 1,50 giây |
| `interrupted_closure` | Sự kiện bị ngắt do mất quan sát, bất đồng mắt, gián đoạn, hiệu chỉnh lại hoặc kết thúc chạy |

`blink_candidate` là ứng viên chớp mắt do heuristic, chưa phải nhãn sự thật. Các giới hạn thời gian chỉ là tham số khởi đầu. Một lần nhắm chủ động vẫn có thể được ghi là prolonged closure.

Cờ dài được ghi ngay khi vượt ngưỡng, không chờ mở mắt. Khi mở lại, mã ghi thêm completed prolonged closure cho cùng sự kiện. **Không cộng hai loại này như hai lần nhắm độc lập.**

Ví dụ về che mặt:

1. Mắt OPEN, sau đó CLOSED → bắt đầu đo.
2. Che mặt → UNKNOWN và ghi interrupted closure đến mốc hợp lệ cuối cùng.
3. Bỏ tay ra khi mắt vẫn nhắm → thấy CLOSED, nhưng chưa biết mốc bắt đầu nên `closure_s` để trống, trên màn hình là `?`.
4. Mở mắt → trở lại OPEN, không hoàn tất một blink từ đoạn bị mất.
5. Nhắm rồi mở tiếp → sự kiện mới có thể được đo.

Tương tự, nếu khoảng cách giữa frame > 0,20 giây, sự kiện bị ngắt. Tại frame hợp lệ sau gián đoạn, trạng thái có thể lập tức là OPEN/CLOSED theo EAR mới; không nối sự kiện cũ qua khoảng trống.

## 8. Bài thử 90 giây

Sau khi hết CALIBRATING, thực hiện lần lượt và ghi chú thời điểm gần đúng:

| Thao tác | Kết quả cần kiểm tra |
| --- | --- |
| Nhìn thẳng, mắt mở khoảng 10 giây | Chủ yếu OPEN, không tăng bộ đếm vô cớ |
| Chớp có chủ đích 5 lần, cách nhau khoảng 2 giây | Bộ đếm tăng tương ứng nếu thời lượng nằm trong khoảng cấu hình |
| Nhắm hai mắt khoảng 2 giây rồi mở | Có LONG CLOSURE khi đang nhắm; có prolonged closure khi mở |
| Khi mắt mở, che mặt khoảng 3 giây rồi bỏ tay | UNKNOWN khi mất mặt; không đếm thời gian che thành nhắm lâu |
| Mắt mở → nhắm → che mặt → bỏ tay khi còn nhắm → mở | Có interrupted closure; không ghép hai đoạn thành blink hoàn chỉnh |
| Mở mắt rồi chớp thêm 2 lần | Bộ đếm hoạt động trở lại |
| Nhìn thẳng đến cuối | OPEN ổn định, chương trình tạo báo cáo |

Thực hiện tại bàn với camera cố định. Bài thử yêu cầu chủ động nhắm mắt, nên không thực hiện trong khi lái xe.

Q/Esc thoát sớm, Ctrl+C dừng từ terminal. Nếu không thấy cửa sổ có thể thử `--headless` để kiểm tra đọc camera, nhưng không có giao diện xác nhận độ bám. Chế độ headless vẫn cần bạn giữ mắt mở lúc hiệu chỉnh.

## 9. Đọc báo cáo

Chương trình không lưu ảnh/video. Mỗi lần chạy tạo ba tệp trong `reports`:

- `eyes_....json`: môi trường, tốc độ, cấu hình/ngưỡng, lịch sử hiệu chỉnh, số sự kiện và trạng thái.
- `eyes_...._frames.csv`: EAR mỗi mắt, phase, trạng thái, thời lượng đang đo, cờ dài và timestamp từng frame.
- `eyes_...._events.csv`: loại sự kiện, mốc bắt đầu/kết thúc, thời lượng và lý do kết thúc/ngắt.

Trong frame CSV, EAR trống là thiếu quan sát, không phải EAR = 0. Thời lượng trống nghĩa là không có sự kiện có mốc bắt đầu đã biết. Khi CLOSED mới xuất hiện sau mất mặt, nó có thể trống dù trạng thái là CLOSED.

Trong JSON, `CALIBRATING:UNKNOWN` không phải lỗi mất tracking. Pha hiệu chỉnh chưa phân loại mắt. `long_closure_flag` và `prolonged_closure` là các bản ghi khác nhau của sự kiện dài như đã giải thích trên.

## 10. Nếu kết quả sai

| Hiện tượng | Thao tác |
| --- | --- |
| File không tìm thấy sau giải nén | Kiểm tra không có thư mục lồng `driver-monitor/driver-monitor` |
| Thiếu module bước 2 | Giải nén bước 2 vào cùng thư mục, dùng đúng `.venv` |
| Mắt mở nhưng CLOSED | Kiểm tra landmarks, ánh sáng, nhấn C để hiệu chỉnh lại |
| Nhắm mà vẫn OPEN | Kiểm tra EAR có giảm không; gửi frame CSV để chọn ngưỡng |
| Chớp bị bỏ sót | Kiểm tra frame gap, bất đồng hai mắt, ngưỡng EAR và thời lượng |
| Che mặt nhưng vẫn OPEN/CLOSED | Model có thể còn suy đoán landmarks; cần cải thiện tầng chất lượng ở bước sau |
| CALIBRATING không kết thúc | Giữ cả hai mắt trong khung, giảm quay đầu, chạy lâu hơn |

Đừng đổi nhiều tham số cùng lúc. Ví dụ, sau khi quan sát được EAR mở và EAR nhắm thực tế, có thể thử:

```powershell
.\.venv\Scripts\python.exe check_eyes.py --camera 0 --seconds 90 --close-ratio 0.70 --open-ratio 0.85
```

Tăng close-ratio làm điều kiện đóng dễ đạt hơn, nhưng có thể tăng nhầm lẫn. Tăng open-ratio làm điều kiện mở lại khó đạt hơn. Hãy thử mặc định trước và giữ báo cáo để so sánh.

## 11. Đọc mã và tiêu chí hoàn thành

Đọc `eye_events.py` trước: `eye_aspect_ratio()` → `classify()` → `update()` → `interrupt()`. Sau đó đọc `Calibration.add()` và vòng lặp `run()` trong check_eyes.py.

Bạn hoàn thành bước 3 khi nạp model được, hiệu chỉnh hoàn tất, mắt mở/nhắm hiển thị hợp lý, các lần chớp có chủ đích được ghi gần đúng, nhắm lâu tạo cờ, và che mặt không bị cộng thành thời gian nhắm. Số chớp tự nhiên không được kiểm chứng chỉ bằng nhìn bộ đếm; để đánh giá định lượng sau này cần nhãn sự kiện.

Gửi JSON cùng cả hai CSV và ghi chú số lần chớp chủ đích, thời điểm che mặt/nhắm lâu. Nếu sai, gửi kết quả trước khi chỉnh ngưỡng. Sau bước này ta bổ sung miệng và tư thế đầu, rồi mới tổng hợp cửa sổ 30 giây.

## 12. Cơ sở nghiên cứu

Soukupová và Čech, “Real-Time Eye Blink Detection using Facial Landmarks”, CVWW 2016:
https://vision.fe.uni-lj.si/cvww2016/proceedings/papers/05.pdf

Nguồn này giới thiệu EAR và phát hiện mẫu chớp theo thời gian bằng SVM. Bước 3 chỉ dùng ý tưởng EAR; các điểm MediaPipe, hiệu chỉnh phân vị, hysteresis, khoảng thời gian và quy tắc hai mắt là thiết kế baseline của dự án, không phải triển khai lại đầy đủ bài báo.

## 13. Phạm vi kiểm tra gói

14 bài kiểm tra logic đã chạy thành công. Luồng chạy và ghi CSV/JSON được kiểm tra với camera/model giả lập, bao gồm nhắm lâu và mất mặt. Môi trường kiểm tra gói không có webcam Windows hay MediaPipe để chạy end-to-end thật. Lệnh `--check` và bài thử camera trên máy bạn là bước xác nhận còn lại.
