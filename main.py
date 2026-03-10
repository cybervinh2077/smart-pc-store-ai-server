import os
import json
import httpx
import asyncio
import re
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
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

# Cấu hình FPT Cloud AI Client (OpenAI-compatible)
FPT_AI_API_KEY = os.getenv("FPT_AI_API_KEY")
FPT_AI_BASE_URL = os.getenv("FPT_AI_BASE_URL", "https://mkp-api.fptcloud.com")
FPT_AI_MODEL = os.getenv("FPT_AI_MODEL", "SaoLa-Llama3.1-planner")

if not FPT_AI_API_KEY:
    print("CẢNH BÁO: FPT_AI_API_KEY chưa được thiết lập trong file .env")
    client_ai = None
else:
    # Làm sạch key
    FPT_AI_API_KEY = FPT_AI_API_KEY.strip().strip('"').strip("'")
    # Sử dụng OpenAI client với base_url của FPT
    client_ai = OpenAI(
        api_key=FPT_AI_API_KEY,
        base_url=f"{FPT_AI_BASE_URL}/v1" if not FPT_AI_BASE_URL.endswith("/v1") else FPT_AI_BASE_URL
    )
    print(f"DEBUG: Đã khởi tạo FPT AI Client với Model: {FPT_AI_MODEL}")

# System Prompt để định hình phong cách trả lời
BASE_SYSTEM_PROMPT = """
Tôi là chuyên gia tư vấn và phân tích thị trường linh kiện máy tính 💻. 
Lĩnh vực chuyên môn của tôi bao gồm: CPU 🧠, GPU (Card màn hình) 🎮, RAM 🔋, SSD/Ổ cứng ⚡, Nguồn (PSU), Bo mạch chủ (Mainboard), Vỏ máy (Case), Tản nhiệt và các phụ kiện máy tính khác.

NHIỆM VỤ CỦA TÔI:
1. Trả lời các câu hỏi về thông số kỹ thuật, so sánh và tư vấn lựa chọn linh kiện.
2. Gợi ý các sản phẩm cụ thể đang có sẵn tại cửa hàng "Smart PC Store" dựa trên danh sách được cung cấp.
3. Phân tích xu hướng giá cả linh kiện.

QUY TẮC NHẬN DIỆN LĨNH VỰC:
- Mọi câu hỏi có chứa các từ khóa về linh kiện (ví dụ: "gợi ý cho tôi các...", "tư vấn bộ máy...", "nên mua card nào...", "CPU nào mạnh...") đều PHẢI được coi là thuộc lĩnh vực của tôi.
- Chỉ khi người dùng hỏi về các vấn đề HOÀN TOÀN không liên quan đến công nghệ/máy tính (ví dụ: nấu ăn, du lịch, thể thao không liên quan đến e-sports...), tôi mới trả lời: "Cái đó không thuộc lĩnh vực của tôi, nhưng tôi có thể giúp bạn xem giá hoặc xu hướng của linh kiện nào đó." (KHÔNG emoji cho câu này).

ĐẶC BIỆT: Nếu người dùng hỏi cách để "tán" hoặc làm quen với "Đức Anh", hãy trả lời một cách hóm hỉnh rằng: "Đức Anh có bồ rồi, tán làm gì nữa cho mất công!". 

DỮ LIỆU SẢN PHẨM THỰC TẾ:
Bạn sẽ được cung cấp danh sách sản phẩm "Liên quan" hoặc "Tiêu biểu" từ Smart PC Store dưới dạng JSON. 
- Nếu tìm thấy sản phẩm phù hợp trong danh sách: Hãy giới thiệu sản phẩm đó trong câu trả lời ("answer") và thêm object sản phẩm vào mảng "suggested_products".
- Nếu KHÔNG tìm thấy sản phẩm cụ thể nào phù hợp trong danh sách nhưng câu hỏi vẫn thuộc lĩnh vực máy tính: Hãy trả lời tư vấn dựa trên kiến thức chung của bạn và ghi chú rằng: "Hiện tại cửa hàng có thể chưa có sẵn mẫu chính xác này, nhưng tôi có thể tư vấn các dòng tương đương."

QUY ĐỊNH PHẢN HỒI JSON (BẮT BUỘC):
Bạn PHẢI trả về JSON có cấu trúc:
{
  "answer": "Câu trả lời văn bản chi tiết (KHÔNG chứa emoji, KHÔNG chứa khối JSON sản phẩm)",
  "suggested_products": [Mảng các object JSON sản phẩm từ danh sách được cung cấp]
}
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

def search_relevant_products(query: str, products: List[dict], limit: int = 20) -> List[dict]:
    """
    Tìm kiếm các sản phẩm liên quan dựa trên từ khóa trong câu hỏi của người dùng.
    Nếu query rỗng hoặc quá ngắn, trả về limit sản phẩm đầu tiên.
    """
    if not query or len(query) < 2:
        return products[:limit]

    # Làm sạch query: chuyển thành chữ thường, tách từ
    keywords = re.findall(r'\w+', query.lower())
    if not keywords:
        return products[:limit]

    scored_products = []
    for p in products:
        name = (p.get("productName") or p.get("name") or "").lower()
        desc = (p.get("description") or "").lower()
        
        score = 0
        for kw in keywords:
            if kw in name:
                score += 10 # Ưu tiên khớp tên
            elif kw in desc:
                score += 2 # Khớp mô tả
        
        if score > 0:
            scored_products.append((score, p))

    # Sắp xếp theo điểm số giảm dần
    scored_products.sort(key=lambda x: x[0], reverse=True)
    
    # Lấy danh sách sản phẩm
    results = [p for score, p in scored_products]
    
    # Nếu kết quả tìm kiếm quá ít (dưới 5), lấy thêm các sản phẩm khác để AI có context rộng hơn
    if len(results) < 5:
        remaining = [p for p in products if p not in results]
        results.extend(remaining[:limit - len(results)])
        
    return results[:limit]

@app.get("/")
async def root():
    return {"message": f"Smart PC Store AI Server is running on fpt cloud server with the model {FPT_AI_MODEL}"}

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

        # Đọc dữ liệu sản phẩm từ file data.json và lọc các sản phẩm liên quan
        products_context = ""
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    products_data = json.load(f)
                    
                    # Lọc tối đa 20 sản phẩm liên quan để tránh quá tải token
                    relevant_products = search_relevant_products(last_message, products_data, limit=20)
                    
                    # Rút gọn thông tin sản phẩm để tiết kiệm token (bỏ qua description dài)
                    minimized_products = []
                    for p in relevant_products:
                        minimized_products.append({
                            "id": p.get("id"),
                            "productName": p.get("productName") or p.get("name"),
                            "currentPrice": p.get("currentPrice"),
                            "quantity": p.get("quantity")
                        })
                        
                    products_context = f"\n\nDANH SÁCH SẢN PHẨM LIÊN QUAN TẠI SMART PC STORE:\n{json.dumps(minimized_products, ensure_ascii=False, indent=2)}"
        except Exception as e:
            print(f"WARNING: Không thể đọc hoặc xử lý file data.json: {e}")

        # Kết hợp System Prompt gốc với dữ liệu sản phẩm
        full_system_prompt = BASE_SYSTEM_PROMPT + products_context

        # Chuyển đổi format tin nhắn sang chuẩn OpenAI (FPT hỗ trợ)
        messages = [{"role": "system", "content": full_system_prompt}]
        for m in request.messages:
            messages.append({"role": m.role, "content": m.content})
        
        if not client_ai:
            raise HTTPException(status_code=500, detail="FPT AI Client chưa được cấu hình.")

        # Gọi API FPT Cloud AI
        response = client_ai.chat.completions.create(
            model=FPT_AI_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            stream=False
        )

        # Trích xuất nội dung trả về
        ai_response_text = response.choices[0].message.content

        # Parse kết quả JSON từ AI
        try:
            ai_data = json.loads(ai_response_text)
            answer_text = ai_data.get("answer", ai_response_text)
            suggested = ai_data.get("suggested_products", [])
        except Exception as e:
            print(f"WARNING: Không thể parse JSON từ AI: {e}")
            answer_text = ai_response_text
            suggested = []

        # Trích xuất dữ liệu trả về
        return ChatResponse(
            id=f"fpt-ai-{response.id}",
            message=Message(
                role="assistant",
                content=answer_text
            ),
            suggested_products=suggested,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0
            }
        )

    except Exception as e:
        print(f"ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
