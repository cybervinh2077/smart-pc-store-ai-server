import os
import json
import httpx
import asyncio
import re
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai
from dotenv import load_dotenv
from supabase import create_client, Client
from markov_predictor import predict_future_prices

# Load biến môi trường từ file .env
load_dotenv()

app = FastAPI(title="smart-pc-store-ai-server")

# Thêm cấu hình CORS để bypass
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cấu hình Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("CẢNH BÁO: SUPABASE_URL hoặc SUPABASE_KEY chưa được thiết lập!")
    supabase: Client = None
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Đường dẫn file dữ liệu linh kiện (vẫn giữ để làm cache hoặc fallback nếu cần)
# Lưu ý: Trên Vercel hoặc Render, thư mục /tmp là nơi duy nhất có quyền ghi nhanh
if os.getenv("VERCEL") or os.getenv("RENDER"):
    DATA_FILE = "/tmp/data.json"
    PRICE_CHANGES_FILE = "/tmp/pricechanges.json"
else:
    DATA_FILE = "data.json"
    PRICE_CHANGES_FILE = "pricechanges.json"

# Đảm bảo các file tồn tại để không gây lỗi khi khởi động
def init_local_cache():
    for f_path in [DATA_FILE, PRICE_CHANGES_FILE]:
        if not os.path.exists(f_path):
            try:
                os.makedirs(os.path.dirname(f_path), exist_ok=True) if os.path.dirname(f_path) else None
                with open(f_path, "w", encoding="utf-8") as f:
                    json.dump([], f)
            except:
                pass

init_local_cache()

@app.on_event("startup")
async def startup_event():
    """
    Sự kiện chạy khi server bắt đầu khởi động:
    1. Lấy dữ liệu sản phẩm từ Supabase lần đầu.
    2. Khởi chạy tác vụ ngầm cập nhật mỗi 5 phút.
    """
    await fetch_data_from_supabase()
    asyncio.create_task(periodic_fetch_data())

async def fetch_data_from_supabase():
    """Hàm lấy dữ liệu từ Supabase và lưu vào file local để làm cache/context"""
    if not supabase:
        print("ERROR: Supabase client chưa được khởi tạo.")
        return

    print("INFO: Đang tải dữ liệu từ Supabase...")
    
    try:
        # 1. Lấy dữ liệu sản phẩm (bảng 'Products')
        prod_resp = supabase.table("Products").select("*").execute()
        products = prod_resp.data
        
        # Tạo map productId -> productName để tra cứu nhanh cho lịch sử giá
        # Dùng cột 'id' chính xác từ bảng Products để làm khóa
        product_names_map = {p.get("id"): p.get("productName") or p.get("name") for p in products}
        
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(products, f, ensure_ascii=False, indent=4)
        print(f"SUCCESS: Đã cập nhật {len(products)} sản phẩm từ Supabase (bảng Products, lấy cột 'id' làm khóa chính).")

        # 2. Lấy lịch sử giá từ bảng 'PurchaseOrders' và 'PurchaseOrderItems'
        try:
            # Lấy thông tin từ PurchaseOrderItems kết hợp với PurchaseOrders (để lấy supplierId và orderDate)
            # Supabase (PostgREST) hỗ trợ lấy thông tin quan hệ bảng (nếu có foreign key)
            # Giả định PurchaseOrderItems có cột purchaseOrderId liên kết với PurchaseOrders(id)
            query = "productId, unitPrice, PurchaseOrders(supplierId, orderDate)"
            hist_resp = supabase.table("PurchaseOrderItems").select(query).execute()
            history = hist_resp.data
        except Exception as e_hist:
            print(f"WARNING: Lỗi khi lấy dữ liệu kết hợp PurchaseOrderItems và PurchaseOrders: {str(e_hist)}")
            # Fallback: Lấy riêng lẻ nếu không JOIN được tự động
            try:
                items_resp = supabase.table("PurchaseOrderItems").select("*").execute()
                items = items_resp.data
                orders_resp = supabase.table("PurchaseOrders").select("*").execute()
                orders = {o["id"]: o for o in orders_resp.data}
                
                history = []
                for item in items:
                    order = orders.get(item.get("purchaseOrderId"), {})
                    history.append({
                        "productId": item.get("productId"),
                        "unitPrice": item.get("unitPrice") or item.get("importPrice"),
                        "PurchaseOrders": {
                            "supplierId": order.get("supplierId"),
                            "orderDate": order.get("orderDate") or order.get("createdAt") or order.get("created_at")
                        }
                    })
            except Exception as e_fallback:
                print(f"ERROR: Không thể lấy dữ liệu lịch sử giá từ PurchaseOrders/Items: {str(e_fallback)}")
                history = []
        
        # Format lại data history khớp với cấu trúc pricechanges.json
        formatted_history = []
        for h in history:
            p_id = h.get("productId")
            order_info = h.get("PurchaseOrders") or {}
            
            # importPrice có thể nằm ở 'unitPrice' (tên cột hay dùng cho Items) hoặc 'importPrice'
            price = h.get("unitPrice") or h.get("importPrice")
            
            # effectiveDate lấy từ orderDate của PurchaseOrders
            date = order_info.get("orderDate") or order_info.get("createdAt") or order_info.get("created_at")
            
            if p_id and price and date:
                formatted_history.append({
                    "productId": p_id,
                    "productName": product_names_map.get(p_id, "Sản phẩm không xác định"),
                    "supplierId": order_info.get("supplierId"),
                    "importPrice": float(price),
                    "effectiveDate": date
                })

        with open(PRICE_CHANGES_FILE, "w", encoding="utf-8") as f:
            json.dump(formatted_history, f, ensure_ascii=False, indent=4)
        print(f"SUCCESS: Đã cập nhật {len(formatted_history)} bản ghi lịch sử giá từ Supabase.")

    except Exception as e:
        print(f"ERROR khi lấy dữ liệu từ Supabase: {str(e)}")

async def periodic_fetch_data():
    """Vòng lặp chạy ngầm cập nhật dữ liệu mỗi 5 phút"""
    while True:
        await asyncio.sleep(300) 
        await fetch_data_from_supabase()

# Cấu hình Gemini Client
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("CẢNH BÁO: GEMINI_API_KEY chưa được thiết lập trong file .env")
else:
    # Làm sạch key
    GEMINI_API_KEY = GEMINI_API_KEY.strip().strip('"').strip("'")
    genai.configure(api_key=GEMINI_API_KEY)
    # In ra 10 ký tự đầu để debug
    print(f"DEBUG: Đã tải Gemini API Key: {GEMINI_API_KEY[:10]}... (Độ dài: {len(GEMINI_API_KEY)})")

# Cố định model muốn sử dụng
FIXED_MODEL = "gemini-2.5-flash" 

# System Prompt để định hình phong cách trả lời
BASE_SYSTEM_PROMPT = """
Tôi là người chuyên phân tích và theo dõi giá linh kiện máy tính 💻 — bao gồm CPU 🧠, GPU 🎮, RAM 🔋, SSD ⚡, nguồn, mainboard và các bộ phận phần cứng khác.
Nhiệm vụ của tôi là cung cấp thông tin chính xác, ngắn gọn và cập nhật, giúp người dùng hiểu rõ giá hiện tại, xu hướng tăng giảm, và sự khác biệt giữa các thương hiệu hoặc thế hệ sản phẩm.

Tôi chỉ trả lời các câu hỏi liên quan đến giá linh kiện hoặc thị trường công nghệ máy tính.
Nếu người dùng hỏi ngoài phạm vi này, tôi sẽ phản hồi lịch sự và không có emoji:
“Cái đó không thuộc lĩnh vực của tôi, nhưng tôi có thể giúp bạn xem giá hoặc xu hướng của linh kiện nào đó.”

Dữ liệu sản phẩm thực tế:
Bạn sẽ được cung cấp danh sách sản phẩm hiện có của cửa hàng Smart PC Store dưới dạng JSON. 
Khi người dùng hỏi về một loại linh kiện nào đó, hãy kiểm tra xem trong danh sách có sản phẩm tương ứng không. 
Nếu có, hãy gợi ý thêm cho người dùng trong câu trả lời văn bản: "Hiện tại chúng tôi đang có sản phẩm [Tên sản phẩm] với giá [Giá tiền] bạn có thể tham khảo".

QUY ĐỊNH PHẢN HỒI:
Bạn PHẢI trả về phản hồi dưới định dạng JSON có cấu trúc như sau:
{
  "answer": "Câu trả lời văn bản của bạn cho người dùng (KHÔNG chứa khối JSON sản phẩm trong này)",
  "suggested_products": [Mảng chứa các object JSON sản phẩm đầy đủ mà bạn muốn gợi ý từ danh sách được cung cấp]
}

Phong cách trả lời:
- Ngắn gọn, rõ ràng, dễ hiểu.
- Không sử dụng emoji trong câu trả lời văn bản ("answer").
- Luôn khách quan, thân thiện và có tính phân tích.
"""

# Model cho dữ liệu đầu vào (JSON)
class Message(BaseModel):
    role: str # 'user' hoặc 'assistant' (Gemini dùng 'user' và 'model')
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]
    # Bỏ model khỏi request để không cần khai báo

class ForecastRequest(BaseModel):
    product_id: str
    days: Optional[int] = 7 # Mặc định là 7 ngày nếu để trống

# Model cho dữ liệu đầu ra (JSON) - Giữ nguyên interface cũ để tránh break client
class ChatResponse(BaseModel):
    id: str
    message: Message
    suggested_products: List[dict] = [] # Tách sản phẩm JSON ra ngoài
    past: Optional[List[dict]] = None   # Lịch sử giá cho dự báo Markov
    future: Optional[List[dict]] = None # Dự báo giá tương lai
    usage: dict

@app.get("/")
async def root():
    return {"message": "Smart PC Store AI Server is running with Gemini!"}

@app.post("/forecast")
async def get_markov_forecast(request: ForecastRequest):
    """
    Route riêng biệt để dự báo giá sản phẩm bằng chuỗi Markov.
    Sử dụng phương thức POST.
    """
    p_id = request.product_id
    days = request.days if request.days is not None else 7
    
    print(f"DEBUG: Nhận yêu cầu dự báo Markov (POST) cho Product ID: {p_id} trong {days} ngày.")
    prediction = predict_future_prices(p_id, days)
    
    if "error" in prediction:
        print(f"DEBUG: Lỗi dự báo: {prediction['error']}")
        raise HTTPException(status_code=404, detail=prediction["error"])
    return prediction

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    try:
        last_message = request.messages[-1].content
        
        # Kiểm tra nếu request là yêu cầu dự báo Markov: ftr-a-b
        match = re.match(r"^ftr-(\d+)-(\d+)$", last_message.strip())
        if match:
            product_id = match.group(1)
            days = int(match.group(2))
            
            prediction = predict_future_prices(product_id, days)
            
            if "error" in prediction:
                return ChatResponse(
                    id="markov-error",
                    message=Message(role="assistant", content=prediction["error"]),
                    suggested_products=[],
                    usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                )
            
            # Trả về kết quả dự báo
            content = f"Dự báo giá cho sản phẩm ID {product_id} trong {days} ngày tới."
            return ChatResponse(
                id="markov-prediction",
                message=Message(role="assistant", content=content),
                suggested_products=[],
                past=prediction["past"],
                future=prediction["future"],
                usage={
                    "prompt_tokens": 0, 
                    "completion_tokens": 0, 
                    "total_tokens": 0
                }
            )

        # Đọc dữ liệu sản phẩm từ file data.json
        products_context = ""
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    products_data = json.load(f)
                    products_context = f"\n\nDANH SÁCH SẢN PHẨM HIỆN CÓ TẠI SMART PC STORE:\n{json.dumps(products_data, ensure_ascii=False, indent=2)}"
        except Exception as e:
            print(f"WARNING: Không thể đọc file data.json: {e}")

        # Kết hợp System Prompt gốc với dữ liệu sản phẩm
        full_system_prompt = BASE_SYSTEM_PROMPT + products_context

        # Chuyển đổi format tin nhắn sang Gemini format
        # Gemini dùng 'role': 'user' hoặc 'model'
        history = []
        for m in request.messages[:-1]:
            role = "user" if m.role == "user" else "model"
            history.append({"role": role, "parts": [m.content]})
        
        last_message = request.messages[-1].content
        
        # Sử dụng model cố định và áp dụng System Instruction động
        # Cấu hình response_mime_type để ép AI trả về JSON
        model = genai.GenerativeModel(
            model_name=FIXED_MODEL,
            system_instruction=full_system_prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        
        # Bắt đầu chat session
        chat = model.start_chat(history=history)
        
        # Gửi tin nhắn
        response = chat.send_message(last_message)

        # Parse kết quả JSON từ AI
        try:
            ai_data = json.loads(response.text)
            answer_text = ai_data.get("answer", response.text)
            suggested = ai_data.get("suggested_products", [])
        except Exception as e:
            print(f"WARNING: Không thể parse JSON từ AI: {e}")
            answer_text = response.text
            suggested = []

        # Trích xuất dữ liệu trả về
        return ChatResponse(
            id="gemini-response",
            message=Message(
                role="assistant",
                content=answer_text
            ),
            suggested_products=suggested,
            usage={
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        )

    except Exception as e:
        print(f"ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
