import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

def list_models():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        print("Không tìm thấy GEMINI_API_KEY trong .env")
        return
        
    key = key.strip().strip('"').strip("'")
    genai.configure(api_key=key)

    print("--- Danh sách các model Gemini khả dụng ---")
    try:
        # Lấy danh sách các model có hỗ trợ sinh nội dung (generateContent)
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f"Model Name: {m.name}")
                print(f"Display Name: {m.display_name}")
                print(f"Description: {m.description}")
                print("-" * 30)
    except Exception as e:
        print(f"Lỗi khi liệt kê model: {e}")

if __name__ == "__main__":
    list_models()
