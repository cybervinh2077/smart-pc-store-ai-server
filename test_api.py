import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

def test_key():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        print("Không tìm thấy GEMINI_API_KEY trong .env")
        return
        
    key = key.strip().strip('"').strip("'")
    print(f"Thử nghiệm với Gemini key: {key[:10]}... (độ dài: {len(key)})")
    
    genai.configure(api_key=key)

    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content("Say hello")
        print(f"Kết nối thành công!")
        print(f"Phản hồi từ Gemini: {response.text}")
    except Exception as e:
        print(f"Lỗi kết nối: {e}")

if __name__ == "__main__":
    test_key()
