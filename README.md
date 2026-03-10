# smart-pc-store-ai-server

Hệ thống Server API AI Chatbot chuyên gia phân tích thị trường linh kiện máy tính, sử dụng FPT Cloud AI API.

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
- Tích hợp FPT Cloud AI (OpenAI-compatible).
- Sử dụng FastAPI để đạt hiệu năng cao.

## Cài đặt

1. **Clone repository:**
   ```bash
   git clone <repository_url>
   cd smart-pc-store-ai-server
   ```

2. **Cài đặt môi trường ảo và dependencies:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Trên Windows dùng: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Cấu hình môi trường:**
   - Tạo file `.env` từ `.env.example`:
     ```bash
     cp .env.example .env
     ```
   - Điền đầy đủ các thông tin:
     - `SUPABASE_URL`: URL dự án Supabase của bạn.
     - `SUPABASE_KEY`: Service Role Key hoặc Anon Key của Supabase.
     - `FPT_AI_API_KEY`: API Key từ FPT Cloud AI Marketplace.
     - `FPT_AI_BASE_URL`: https://mkp-api.fptcloud.com
     - `FPT_AI_MODEL`: SaoLa-Llama3.1-planner (hoặc model khác được hỗ trợ).

## Cấu trúc Database (Supabase)
Server mong đợi các bảng sau tồn tại trong Supabase:
- **`products`**: Chứa thông tin sản phẩm linh kiện.
- **`supplier_quotation_history`**: Chứa lịch sử thay đổi giá của các nhà cung cấp.
  - Các trường cần thiết: `product_id`, `product_name`, `supplier_id`, `import_price`, `effective_date`.

## Chạy Server
```bash
python main.py
```
Server sẽ chạy mặc định tại `http://localhost:8000`.

## Các Model hỗ trợ
Hệ thống sử dụng các model Large Language Model (LLM) từ FPT Cloud AI. Mặc định sử dụng `SaoLa-Llama3.1-planner`.

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
   - Nội dung mẫu:
     ```json
     {
       "messages": [
         {"role": "user", "content": "Chào AI, bạn có thể giúp tôi build PC không?"}
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
  "id": "fpt-ai-xxx",
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
    "prompt_tokens": 100,
    "completion_tokens": 50,
    "total_tokens": 150
  }
}
```
