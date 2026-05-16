# Browser tools

## Phân tích `source.ipynb`

Notebook `source.ipynb` đang là một flow thử nghiệm Playwright:

- Tìm executable của Chrome/Edge/Firefox trên máy local.
- Khởi tạo `PlaywrightHandler` với Chrome profile riêng, proxy, anti-fingerprint và tùy chọn giữ profile.
- Mở page bằng profile đó, truy cập một danh sách retailer của 11st.
- Có bước thử nghiệm solver reCAPTCHA và click xác nhận trên UI 11st.

Phần có thể tái sử dụng cho tool mới là `PlaywrightHandler`: nó đã xử lý lifecycle browser, profile, proxy middleware, CDP và emulation. Vì vậy tool Threads mới dùng lại handler này thay vì copy logic notebook.

## Tool auto comment Threads

File `threads_auto_comment.py` cung cấp CLI script để gửi comment vào các Threads post URL đã cung cấp sẵn.

Các giới hạn có chủ ý:

- Chỉ chạy với profile trình duyệt do bạn đăng nhập thủ công.
- Không tự giải CAPTCHA/challenge, không bypass rate-limit, không tự tìm mục tiêu để spam.
- Mặc định giữ profile (`--browser-id`) để bạn đăng nhập một lần rồi tái sử dụng.
- Có `--dry-run`, `--max-comments`, `--min-delay`, `--max-delay` để kiểm soát batch.

### Cài đặt

```bash
uv sync
uv run playwright install chromium
```

### Chạy thử không gửi comment

```bash
uv run python threads_auto_comment.py \
  --post-url "https://www.threads.net/@example/post/POST_ID" \
  --comment "Nội dung comment" \
  --dry-run
```

### Chạy thật

Lần đầu nên chạy không headless để đăng nhập Threads trong cửa sổ Chrome:

```bash
uv run python threads_auto_comment.py \
  --browser-id 20 \
  --post-url-file data/threads_posts.txt \
  --comments-file data/threads_comments.txt \
  --max-comments 5 \
  --min-delay 30 \
  --max-delay 90
```

Sau khi profile đã đăng nhập, có thể thêm `--headless` nếu môi trường hỗ trợ.

### Định dạng input file

`data/threads_posts.txt`:

```text
https://www.threads.net/@example/post/POST_ID_1
https://www.threads.net/@example/post/POST_ID_2
```

`data/threads_comments.txt`:

```text
Comment 1
Comment 2
```

## Ghi chú ffmpeg

Trên Windows có thể cài ffmpeg bằng:

```powershell
winget install -e --id Gyan.FFmpeg
```
