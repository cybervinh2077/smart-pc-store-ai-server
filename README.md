# Smart PC Store AI Server

Hệ thống Server API AI Chatbot chuyên gia phân tích thị trường linh kiện máy tính, sử dụng Google Gemini API.

## Tính năng
- AI đóng vai trò Chuyên gia phân tích thị trường công nghệ (CPU, GPU, RAM, v.v.).
- **Gợi ý sản phẩm thông minh:** AI tự động đọc dữ liệu từ `data.json` để đưa ra các gợi ý sản phẩm thực tế kèm theo mã JSON của sản phẩm đó dựa trên câu hỏi của người dùng.
- **Dự báo giá Markov:** 
    - Lệnh `ftr-a-b` (trong chat): Dự báo giá sản phẩm a cho b ngày tiếp theo.
    - **Endpoint riêng biệt:** `POST /forecast` để lấy dữ liệu dự báo.
        - Body: `{"product_id": "1", "days": 7}`
        - Nếu `days` để trống, mặc định sẽ là 7 ngày.
- **Tự động cập nhật dữ liệu định kỳ:** 
    - Lấy dữ liệu lần đầu ngay khi server khởi động.
    - Tự động lấy danh sách sản phẩm và **lịch sử thay đổi giá** (từ URL `supplier-quotations/history`) cho từng sản phẩm.
    - Dữ liệu sản phẩm được lưu vào `data.json`, lịch sử giá được lưu vào `pricechanges.json`.
    - Tự động cập nhật định kỳ mỗi **3 phút**.
- Tự động áp dụng System Prompt để định hình phong cách trả lời chuyên nghiệp (không emoji).
- API nhận và trả dữ liệu dạng JSON.
- Tích hợp Google Gemini AI (Free tier).
- Sử dụng FastAPI để đạt hiệu năng cao.

## Cài đặt

1. **Clone repository:**
   ```bash
   git clone <repository_url>
   cd Smart-PC-Store-AI-Server
   ```

2. **Cài đặt môi trường ảo (khuyến nghị):**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Trên Windows dùng: venv\Scripts\activate
   ```

3. **Cài đặt dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Cấu hình môi trường:**
   - Tạo file `.env` từ `.env.example`:
     ```bash
     cp .env.example .env
     ```
   - Điền `GEMINI_API_KEY` của bạn vào file `.env`.

## Chạy Server
```bash
python main.py
```
Server sẽ chạy mặc định tại `http://localhost:8000`.

## Các Model hỗ trợ
Để xem danh sách đầy đủ các model mà Gemini API hỗ trợ trong tài khoản của bạn, hãy chạy script:
```bash
python list_models.py
```

Các model phổ biến thường dùng:
- `gemini-2.5-flash`: (Đã khóa cứng) Phiên bản model mới nhất theo cấu hình của bạn.

Hệ thống đã được thiết lập để luôn sử dụng `gemini-2.5-flash`, bạn không cần truyền tham số `model` trong request body nữa.

## API Documentation
Sau khi chạy server, bạn có thể xem tài liệu API tại:
- Swagger UI: `http://localhost:8000/docs`
- Redoc: `http://localhost:8000/redoc`

## Hướng dẫn Test với Postman

Để kiểm tra API bằng Postman, hãy làm theo các bước sau:

1. **Phương thức (Method):** Chọn `POST`.
2. **URL:** Nhập `http://localhost:8000/chat`.
3. **Headers:** 
   - Key: `Content-Type`, Value: `application/json`.
4. **Body:**
   - Chọn tab **Body** -> **raw** -> **JSON**.
   - Nội dung mẫu (không cần field model):
     ```json
     {
       "messages": [
         {"role": "user", "content": "Chào Gemini, bạn có thể giúp tôi build PC không?"}
       ]
     }
     ```
5. **Gửi (Send):** Nhấn nút **Send** và kiểm tra kết quả trả về.

### Endpoint: `POST /chat`
**Request Body:**
```json
{
  "messages": [
    {"role": "user", "content": "Tư vấn cho tôi cấu hình PC chơi game tầm 20 triệu."}
  ]
}
```

**Response Body:**
```json
{
  "id": "gemini-response",
  "message": {
    "role": "assistant",
    "content": "Hiện tại chúng tôi đang có sản phẩm Màn hình Dell 24 inch..."
  },
  "suggested_products": [
    {
      "id": "prod_001",
      "name": "Màn hình Dell 24 inch",
      "price": 3500000,
      "category": "Monitor"
    }
  ],
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```
