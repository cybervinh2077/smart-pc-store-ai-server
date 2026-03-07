import os
import json
import httpx
import asyncio
import re
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import google.generativeai as genai
from dotenv import load_dotenv
from markov_predictor import predict_future_prices

# Load biến môi trường từ file .env
load_dotenv()

app = FastAPI(title="Smart PC Store AI Server")

# Đường dẫn file dữ liệu linh kiện
DATA_FILE = "data.json"
PRICE_CHANGES_FILE = "pricechanges.json"

@app.on_event("startup")
async def startup_event():
    """
    Sự kiện chạy khi server bắt đầu khởi động:
    1. Lấy dữ liệu sản phẩm lần đầu ngay lập tức.
    2. Khởi chạy tác vụ ngầm cập nhật mỗi 3 phút.
    """
    # Lấy dữ liệu lần đầu tiên ngay lập tức
    await fetch_products_data()
    
    # Khởi chạy tác vụ chạy ngầm cập nhật định kỳ mỗi 3 phút (180 giây)
    asyncio.create_task(periodic_fetch_data())

async def fetch_products_data():
    """Hàm thực hiện fetch dữ liệu sản phẩm và lưu vào data.json"""
    url = "http://localhost:8080/smart_pc_store_war/products"
    payload = {
        "username": "tester",
        "password": "Abc123@"
    }
    
    print(f"INFO: Đang tải dữ liệu sản phẩm từ {url}...")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.request("GET", url, json=payload, timeout=15.0)
            
            if response.status_code == 200:
                products = response.json()
                with open(DATA_FILE, "w", encoding="utf-8") as f:
                    json.dump(products, f, ensure_ascii=False, indent=4)
                print(f"SUCCESS: Đã cập nhật dữ liệu vào {DATA_FILE}")
                
                # Sau khi có dữ liệu sản phẩm, tiếp tục lấy lịch sử giá cho từng sản phẩm
                await fetch_price_histories(products)
            else:
                print(f"WARNING: Không thể lấy dữ liệu sản phẩm. Status code: {response.status_code}")
                if not os.path.exists(DATA_FILE):
                    with open(DATA_FILE, "w") as f: json.dump([], f)
    except Exception as e:
        print(f"ERROR khi lấy dữ liệu sản phẩm: {str(e)}")
        if not os.path.exists(DATA_FILE):
            with open(DATA_FILE, "w") as f: json.dump([], f)

async def fetch_price_histories(products):
    """Lấy lịch sử thay đổi giá cho toàn bộ danh sách sản phẩm"""
    print("INFO: Đang bắt đầu lấy lịch sử giá cho các sản phẩm...")
    all_price_changes = []
    
    async with httpx.AsyncClient() as client:
        for p in products:
            # Lấy supplierId và id (là productId) từ object sản phẩm dựa trên mẫu bạn cung cấp
            s_id = p.get("supplierId")
            p_id = p.get("id") # Bạn đính chính: productId thực chất là id
            p_name = p.get("productName")
            
            if s_id is not None and p_id is not None:
                # URL: .../history?productId=yyy&supplierId=xxx
                history_url = f"http://localhost:8080/smart_pc_store_war/supplier-quotations/history?productId={p_id}&supplierId={s_id}"
                try:
                    resp = await client.get(history_url, timeout=10.0)
                    if resp.status_code == 200:
                        history_data = resp.json()
                        if isinstance(history_data, list):
                            for record in history_data:
                                # Trích xuất các trường: productId, productName, supplierId, importPrice, effectiveDate
                                change_entry = {
                                    "productId": p_id,
                                    "productName": p_name,
                                    "supplierId": s_id,
                                    "importPrice": record.get("importPrice"),
                                    "effectiveDate": record.get("effectiveDate")
                                }
                                all_price_changes.append(change_entry)
                except Exception as e:
                    print(f"ERROR khi lấy lịch sử giá cho Product {p_id}: {str(e)}")

    # Lưu toàn bộ dữ liệu vào pricechanges.json
    try:
        with open(PRICE_CHANGES_FILE, "w", encoding="utf-8") as f:
            json.dump(all_price_changes, f, ensure_ascii=False, indent=4)
        print(f"SUCCESS: Đã lưu {len(all_price_changes)} bản ghi vào {PRICE_CHANGES_FILE}")
    except Exception as e:
        print(f"ERROR khi lưu file {PRICE_CHANGES_FILE}: {str(e)}")

async def periodic_fetch_data():
    """Vòng lặp chạy ngầm cập nhật dữ liệu mỗi 3 phút"""
    while True:
        await asyncio.sleep(180) # Đợi 3 phút
        print("INFO: Bắt đầu cập nhật dữ liệu sản phẩm định kỳ (mỗi 3 phút)...")
        await fetch_products_data()

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
