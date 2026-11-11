# Sân pickleball toàn Việt Nam — danh sách ứng viên

Dữ liệu được cào từ Google Maps ngày **11/11/2026** để **duyệt thủ công** trước khi nhập vào app. Không có gì được ghi vào database.

## File

| File | Nội dung |
|---|---|
| `courts-candidates.csv` | **2.040 sân** ứng viên, theo cột của bảng `courts` (UTF-8 có BOM, mở được bằng Excel) |
| `loai-bo.csv` | 97 địa điểm bị loại, kèm lý do (UTF-8 có BOM) |
| `tinh-34.csv` | 34 tỉnh/thành mới theo Nghị quyết 202/2025/QH15 (hiệu lực 1/7/2025), kèm tên tỉnh cũ và nguồn |
| `queries.txt`, `queries-manifest.csv` | 254 truy vấn đã chạy (id, loại, tỉnh, depth, lưới toạ độ) |
| `queries-retry.csv` | 26 truy vấn chạy lại có `-geo` (xem phần “Lỗi gặp phải”) |
| `raw/batch-*.jsonl`, `raw/retry-*.jsonl` | Output thô của từng lô, **đã bỏ** review, tên người review, ảnh, email và id chủ sở hữu |
| `raw/batches.csv` | Nhật ký từng lô: truy vấn, số kết quả, số lỗi, thời gian, lệnh |
| `clean-stats.json` | Số liệu thống kê dùng trong README này |

## Lệnh đã chạy

```bash
go build -o bin/gms .

# Bước 1: sinh truy vấn từ out/tinh-34.csv
python3 scripts/pickleball/gen_queries.py

# Bước 2: 19 lô (≤ 20 truy vấn/lô), -c 2, nghỉ 45 giây giữa các lô
python3 scripts/pickleball/run_batches.py
#   mỗi lô gọi: bin/gms -input <lô> -results <tmp>.json -json -lang vi -depth <2|3> -c 2 -exit-on-inactivity 90s
#   lô lưới:   ... -depth 1 -grid-bbox <bbox> -grid-cell 4 -zoom 14

# Chạy lại các truy vấn lỗi, có -geo <tâm tỉnh/quận> -zoom 12|14, nghỉ 30 giây giữa các lô
GMS_MANIFEST=out/queries-retry.csv GMS_BATCH_PREFIX=retry GMS_PAUSE_S=30 \
  python3 scripts/pickleball/run_batches.py

# Bước 3: làm sạch
python3 scripts/pickleball/clean_courts.py
```

Không bật `-email` hay `-extra-reviews`. Trang chi tiết của Google luôn trả kèm vài review, nên `run_batches.py` lọc bỏ chúng ngay sau mỗi lô và xoá file thô chưa lọc.

Môi trường chạy: playwright-go cần driver 1.57.0 nhưng CDN cũ trả 404, nên driver được lắp từ gói npm `playwright-core@1.57.0`, với `PLAYWRIGHT_DRIVER_PATH` và `PLAYWRIGHT_BROWSERS_PATH` trỏ vào thư mục tạm.

## Truy vấn

| Loại | Số truy vấn | Mẫu |
|---|---:|---|
| Tỉnh mới | 102 | `sân pickleball <tỉnh>`, `pickleball <tỉnh>`, `pickleball court <tỉnh>` (depth 3) |
| Tỉnh cũ | 60 | `sân pickleball <tỉnh cũ>`, `pickleball <tỉnh cũ>` (depth 2) |
| Quận/huyện cũ của 5 thành phố | 87 | `sân pickleball <quận>, <thành phố>` (depth 2) |
| Lưới toạ độ | 5 | `sân pickleball`, ô lưới 4 km, zoom 14, phủ nội đô HCM, Hà Nội, Đà Nẵng, Hải Phòng, Cần Thơ |
| **Tổng** | **254** | + 26 truy vấn chạy lại |

## Từ dữ liệu thô đến danh sách cuối

| Bước | Số dòng |
|---|---:|
| Kết quả thô (mọi lô, gồm cả trùng giữa các truy vấn) | 3.134 |
| Sau gộp theo `place_id` | 2.137 |
| Sau lọc (đúng là sân pickleball) | 2.052 |
| Sau gộp trùng (tên giống và cách nhau < 150 m) | **2.040** |

Lý do loại (`loai-bo.csv`):

| Lý do | Số |
|---|---:|
| Cửa hàng / nhà cung cấp dụng cụ | 45 |
| Không liên quan pickleball (sân cầu lông, sân bóng, … không nhắc pickleball) | 34 |
| Trùng (tên giống, cách < 150 m) | 12 |
| Tên cho thấy là cửa hàng dụng cụ | 3 |
| Không có toạ độ | 1 |
| Sân tennis thuần | 1 |
| Huấn luyện viên / lớp học | 1 |

## Số sân theo `province_new`

| # | province_new | Số sân | high | medium | low |
|---|---|---:|---:|---:|---:|
| 1 | Hồ Chí Minh | 424 | 189 | 108 | 127 |
| 2 | Hà Nội | 311 | 175 | 87 | 49 |
| 3 | Đà Nẵng | 142 | 70 | 30 | 42 |
| 4 | Hải Phòng | 104 | 29 | 54 | 21 |
| 5 | Phú Thọ | 59 | 23 | 21 | 15 |
| 6 | Lâm Đồng | 55 | 18 | 21 | 16 |
| 7 | Đồng Nai | 54 | 17 | 21 | 16 |
| 8 | Bắc Ninh | 51 | 26 | 18 | 7 |
| 9 | Gia Lai | 51 | 16 | 17 | 18 |
| 10 | Cần Thơ | 50 | 14 | 9 | 27 |
| 11 | An Giang | 45 | 13 | 16 | 16 |
| 12 | Hưng Yên | 44 | 14 | 18 | 12 |
| 13 | Tây Ninh | 43 | 11 | 19 | 13 |
| 14 | Đắk Lắk | 43 | 22 | 9 | 12 |
| 15 | Ninh Bình | 42 | 19 | 12 | 11 |
| 16 | Khánh Hòa | 39 | 15 | 14 | 10 |
| 17 | Quảng Ninh | 39 | 16 | 14 | 9 |
| 18 | Quảng Ngãi | 37 | 19 | 9 | 9 |
| 19 | Hà Tĩnh | 36 | 8 | 15 | 13 |
| 20 | Quảng Trị | 36 | 15 | 13 | 8 |
| 21 | Đồng Tháp | 36 | 9 | 13 | 14 |
| 22 | Thanh Hóa | 34 | 11 | 17 | 6 |
| 23 | Nghệ An | 32 | 13 | 13 | 6 |
| 24 | Lào Cai | 29 | 6 | 14 | 9 |
| 25 | Cà Mau | 28 | 11 | 11 | 6 |
| 26 | Thái Nguyên | 28 | 10 | 13 | 5 |
| 27 | Vĩnh Long | 28 | 12 | 9 | 7 |
| 28 | Huế | 27 | 10 | 9 | 8 |
| 29 | Lạng Sơn | 24 | 4 | 15 | 5 |
| 30 | Tuyên Quang | 24 | 7 | 10 | 7 |
| 31 | Sơn La | 20 | 8 | 9 | 3 |
| 32 | Cao Bằng | 15 | 5 | 6 | 4 |
| 33 | Điện Biên | 6 | 1 | 1 | 4 |
| 34 | Lai Châu | 4 | 0 | 4 | 0 |

**Không có tỉnh nào có 0 sân.** Điện Biên lúc đầu không ra kết quả vì truy vấn “sân pickleball Điện Biên” bị lỗi tải trang. Chạy lại có `-geo` thì ra thêm sân, và truy vấn “pickleball Điện Biên” cũng có kết quả. Hai tỉnh Điện Biên (6 sân) và Lai Châu (4 sân) có rất ít sân, nên kiểm tra thêm nếu cần.

## Mức tin cậy (`confidence`)

- **high (836)**: danh mục chính trên Google là “Sân pickleball”.
- **medium (669)**: danh mục phụ là “Sân pickleball”, hoặc tên có “pickleball” và danh mục là sân thể thao (tổ hợp thể thao, sân chơi, sân tennis, …), hoặc CLB thể thao có chữ “Sân/Court” trong tên.
- **low (535)**: tên có pickleball nhưng danh mục là “Câu lạc bộ thể thao” và tên không ghi rõ là sân (có thể chỉ là CLB, không có sân riêng); hoặc danh mục lạ (quán cà phê, xưởng, cửa hàng có chữ “Sân”); hoặc chỉ phần mô tả nhắc tới pickleball. **Nên duyệt kỹ nhóm này.**

## Cột kém tin cậy / cần lưu ý

| Cột | Ghi chú |
|---|---|
| `price_per_hour` | **Luôn trống.** Google Maps không có dữ liệu giá; script chỉ điền khi mô tả ghi rõ “…đ/giờ” và không gặp trường hợp nào. |
| `booking_url` | Chỉ 78 dòng, đều là trang đặt sân thật (`datlich.alobo.vn`, `datlich.net`, `datsan.club`, …). Link Facebook/Zalo/website khác nằm trong `notes` (dạng `website: …`). |
| `hours_open` / `hours_close` | Có ở 1.571 dòng. Nếu giờ khác nhau theo ngày, lấy khung phổ biến nhất và ghi đủ trong `notes`. “Mở cửa cả ngày” được ghi là `00:00`–`23:59`. Nhiều khung trong một ngày thì lấy giờ mở sớm nhất và giờ đóng muộn nhất (ghi đủ trong `notes`). |
| `province_old` | Chỉ 10 dòng: hầu hết địa chỉ trên Google đã dùng tên tỉnh mới. Cột này chỉ được điền khi địa chỉ còn ghi tên tỉnh cũ. |
| `province_new` / `city` | Suy từ thành phần cuối của địa chỉ (2.036 dòng). 1 dòng suy từ sân gần nhất (< 15 km) và 3 dòng suy từ truy vấn, đều có ghi chú trong `notes`. |
| `phone` | Có ở 1.629 dòng, định dạng `+84 …` như trên Google. |
| `rating`, `rating_count` | Lấy từ Google tại thời điểm cào, thay đổi theo thời gian. |
| `category` | Danh mục chính trên Google, do chủ địa điểm tự chọn. Nhiều sân để “Câu lạc bộ thể thao”. |
| `retrieved_at` | Thời điểm bắt đầu lô cào chứa dòng đó (UTC). |
| `google_maps_url` | Dạng ổn định `https://www.google.com/maps/search/?api=1&query=<tên>&query_place_id=<place_id>`. |

## Lỗi gặp phải

- **Không gặp captcha hay bị chặn.** Không đổi IP, không dùng proxy.
- **IP ra ngoài của môi trường chạy đặt ở Mỹ.** Với 27/254 truy vấn, trang kết quả của Maps không tải danh sách (bản đồ mặc định hiện nước Mỹ) và scraper báo lỗi `scrollHeight`. 26 truy vấn trong số đó (trừ lưới Hà Nội, vốn đã có toạ độ) được chạy lại với cờ `-geo` có sẵn của repo, đặt tâm bản đồ vào tỉnh/quận tương ứng: 21 truy vấn ra kết quả.
- 5 truy vấn vẫn không ra kết quả sau khi chạy lại: `sân pickleball Đồng Nai`, `pickleball Hậu Giang`, `sân pickleball Cầu Giấy, Hà Nội`, `sân pickleball Dương Kinh, Hải Phòng`, `sân pickleball Thốt Nốt, Cần Thơ`. Các khu vực này vẫn được phủ bởi truy vấn khác (Đồng Nai 54 sân; Cầu Giấy nằm trong lưới Hà Nội; Hậu Giang qua “sân pickleball Hậu Giang” và “Cần Thơ”).
- Lưới Hà Nội: 5/25 ô lỗi tải trang. Nội đô Hà Nội vẫn được phủ bởi 25 truy vấn theo quận/huyện.
- Kết quả mỗi truy vấn trên Maps bị giới hạn (~20 kết quả mỗi lần cuộn, tối đa vài lần cuộn), nên các tỉnh lớn có thể vẫn còn sót sân ít review. Muốn phủ dày hơn thì thêm truy vấn theo phường, hoặc tăng `-depth`.
