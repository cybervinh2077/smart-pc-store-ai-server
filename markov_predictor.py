import json
import os
import numpy as np
from datetime import datetime, timedelta

def get_price_changes_file():
    if os.getenv("VERCEL") or os.getenv("RENDER"):
        return "/tmp/pricechanges.json"
    return "pricechanges.json"

def predict_future_prices(product_id, days_to_forecast):
    """
    Dự báo giá tương lai bằng chuỗi Markov dựa trên lịch sử giá.
    Trạng thái Markov ở đây được xác định là tỷ lệ thay đổi giá (price change percentage).
    """
    file_path = get_price_changes_file()
    if not os.path.exists(file_path):
        # Trả về lỗi thân thiện thay vì làm hỏng app
        return {"error": f"Dữ liệu lịch sử ({file_path}) chưa sẵn sàng. Vui lòng thử lại sau vài giây."}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            all_data = json.load(f)
    except Exception as e:
        return {"error": f"Lỗi khi đọc dữ liệu lịch sử: {str(e)}"}

    # Lọc lịch sử giá của sản phẩm cụ thể
    product_history = [
        item for item in all_data 
        if str(item.get("productId")) == str(product_id)
    ]

    if not product_history:
        return {"error": f"Không tìm thấy lịch sử giá cho sản phẩm ID {product_id}"}

    # Sắp xếp theo ngày tăng dần
    # Giả sử effectiveDate có định dạng ISO hoặc tương tự mà sort được
    product_history.sort(key=lambda x: x.get("effectiveDate", ""))
    
    past_prices = [
        {
            "date": item.get("effectiveDate"),
            "price": item.get("importPrice")
        } 
        for item in product_history
    ]

    # Nếu chỉ có 1 hoặc ít bản ghi, không đủ để tạo chuỗi Markov
    if len(past_prices) < 3:
        # Dự báo đơn giản: lấy giá cuối cùng
        last_price = past_prices[-1]["price"]
        future = []
        last_date = datetime.now()
        for i in range(1, days_to_forecast + 1):
            next_date = (last_date + timedelta(days=i)).strftime("%Y-%m-%d")
            future.append({"date": next_date, "price": last_price})
        return {"past": past_prices, "future": future, "note": "Dữ liệu quá ít để dùng Markov, dự báo giữ nguyên giá."}

    # Tính toán tỷ lệ thay đổi giá giữa các lần cập nhật
    changes = []
    for i in range(1, len(past_prices)):
        p1 = past_prices[i-1]["price"]
        p2 = past_prices[i]["price"]
        if p1 != 0:
            changes.append((p2 - p1) / p1)
        else:
            changes.append(0)

    # Phân nhóm các thay đổi thành các trạng thái (States)
    # Giảm mạnh (<-5%), Giảm nhẹ (-5% đến -1%), Giữ nguyên (-1% đến 1%), Tăng nhẹ (1% đến 5%), Tăng mạnh (>5%)
    def get_state(change):
        if change < -0.05: return 0
        if change < -0.01: return 1
        if change <= 0.01: return 2
        if change <= 0.05: return 3
        return 4

    states = [get_state(c) for c in changes]
    num_states = 5
    
    # Xây dựng ma trận xác suất chuyển trạng thái (Transition Matrix)
    transition_matrix = np.zeros((num_states, num_states))
    for i in range(len(states) - 1):
        transition_matrix[states[i]][states[i+1]] += 1

    # Chuẩn hóa ma trận (biến số lần xuất hiện thành xác suất)
    for i in range(num_states):
        row_sum = np.sum(transition_matrix[i])
        if row_sum > 0:
            transition_matrix[i] /= row_sum
        else:
            # Nếu trạng thái i chưa bao giờ chuyển sang trạng thái khác trong dữ liệu quá khứ,
            # chúng ta giả định nó có xu hướng quay về trạng thái "Giữ nguyên" (trạng thái 2)
            # hoặc duy trì chính nó. Ở đây chọn xác suất cao cho việc giữ nguyên.
            transition_matrix[i][2] = 0.7
            transition_matrix[i][i] = 0.3 # Tự giữ lấy trạng thái hiện tại một phần

    # Dự báo tương lai
    future_prices = []
    current_price = past_prices[-1]["price"]
    current_state = states[-1]
    
    # Tính giá trị thay đổi trung bình của mỗi trạng thái từ dữ liệu thực tế thay vì dùng hằng số
    # Điều này giúp dự báo bám sát đặc thù của từng sản phẩm hơn
    state_avg_changes = [0.0] * num_states
    for s in range(num_states):
        vals = [changes[i] for i in range(len(states)) if states[i] == s]
        if vals:
            state_avg_changes[s] = sum(vals) / len(vals)
        else:
            # Giá trị mặc định nếu trạng thái đó chưa từng xuất hiện
            defaults = [-0.07, -0.03, 0.0, 0.03, 0.07]
            state_avg_changes[s] = defaults[s]
    
    last_date_str = past_prices[-1]["date"]
    try:
        # Cố gắng parse date, nếu fail thì dùng date hiện tại
        last_date = datetime.fromisoformat(last_date_str.replace("Z", "+00:00"))
    except:
        last_date = datetime.now()

    for i in range(1, days_to_forecast + 1):
        # Chọn trạng thái tiếp theo dựa trên xác suất
        next_state = np.random.choice(num_states, p=transition_matrix[current_state])
        
        # Áp dụng thay đổi giá của trạng thái đó từ trung bình thực tế đã tính
        change_rate = state_avg_changes[next_state]
        current_price = current_price * (1 + change_rate)
        
        next_date = (last_date + timedelta(days=i)).strftime("%Y-%m-%d")
        future_prices.append({
            "date": next_date,
            "price": round(current_price, 2)
        })
        current_state = next_state

    return {
        "past": past_prices,
        "future": future_prices
    }
