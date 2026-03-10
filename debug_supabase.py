import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def test_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Missing Supabase credentials")
        return

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 1. Thử lấy danh sách bảng thực tế từ schema cache (nếu có thể)
    # Hoặc đơn giản là thử query với count exact
    tables_to_test = ["Products", "products", "Product", "product", "PurchaseOrderItems", "PurchaseOrders"]
    
    print(f"--- Đang kiểm tra dữ liệu trong các bảng ---")
    for table in tables_to_test:
        try:
            # Sử dụng count='exact' để lấy tổng số dòng thực tế
            resp = supabase.table(table).select("*", count="exact").execute()
            count = resp.count
            print(f"Bảng '{table}': {count} dòng.")
            if count > 0:
                print(f"   Dữ liệu mẫu 1 dòng: {resp.data[0]}")
        except Exception as e:
            # In lỗi chi tiết từ PostgREST
            print(f"Lỗi khi truy cập bảng '{table}': {str(e)}")

    # 2. Kiểm tra RLS (Row Level Security)
    print(f"\n--- Kiểm tra RLS ---")
    print("Nếu bảng có dòng nhưng trả về 0 dòng và không có lỗi, có thể RLS đang bật mà chưa có Policy cho Anon Key.")

if __name__ == "__main__":
    test_supabase()
