import os
import glob
import requests
from apify_client import ApifyClient
from google import genai

# 환경 변수 로드
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
APIFY_API_TOKEN = os.environ.get("APIFY_API_TOKEN")
TARGET_USER = os.environ.get("TARGET_INSTA_USER")

LAST_POST_FILE = "last_post.txt"

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

def get_last_processed_id():
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""

def save_processed_id(post_id):
    with open(LAST_POST_FILE, "w", encoding="utf-8") as f:
        f.write(post_id)

def download_video(url, output_path):
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)
        return True
    return False

def get_latest_reels_apify():
    print(f"[{TARGET_USER}] Apify API로 최신 게시물 조회 중...")
    client = ApifyClient(APIFY_API_TOKEN)

    # Instagram Scraper Actor 실행 (최신 게시물 1개 추출)
    run_input = {
        "directUrls": [f"https://www.instagram.com/{TARGET_USER}/"],
        "resultsLimit": 1,
        "resultsType": "posts"
    }

    try:
        run = client.actor("apify/instagram-scraper").call(run_input=run_input)
        dataset_items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

        if not dataset_items:
            print("게시글을 찾을 수 없습니다.")
            return None, None, None

        latest_item = dataset_items[0]
        current_post_id = str(latest_item.get("id") or latest_item.get("shortCode"))
        last_post_id = get_last_processed_id()

        # 중복 체크
        if current_post_id and current_post_id == last_post_id:
            print(f"이미 처리된 게시물입니다. (Post ID: {current_post_id})")
            return None, None, None

        # 영상 URL 추출 및 다운로드
        video_url = latest_item.get("videoUrl")
        caption = latest_item.get("caption", "")

        if not video_url:
            print("최신 게시물이 영상(릴스)이 아닙니다.")
            return None, None, None

        os.makedirs("downloads", exist_ok=True)
        video_path = f"downloads/{current_post_id}.mp4"
        
        print("영상 파일 다운로드 중...")
        if download_video(video_url, video_path):
            return video_path, caption, current_post_id

    except Exception as e:
        print(f"Apify 처리 중 에러 발생: {e}")
        return None, None, None

    return None, None, None

def analyze_video_with_gemini(video_path, caption):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    print("Gemini API에 영상 업로드 중...")
    video_file = client.files.upload(file=video_path)
    
    prompt = f"""
다음은 인스타그램 릴스 영상과 게시글 본문입니다.
[게시글 본문]
{caption if caption else '본문 없음'}

영상 콘텐츠와 본문을 종합하여 다음 양식으로 정돈하여 답변해줘:
1. 🎬 **영상 핵심 요약** (3줄 이내)
2. 🔑 **주요 키워드** (3~5개)
3. 💡 **시청 포인트 및 인사이트**
"""

    print("Gemini 영상 분석 진행 중...")
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[video_file, prompt]
    )
    
    client.files.delete(name=video_file.name)
    return response.text

def main():
    if not all([GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, APIFY_API_TOKEN, TARGET_USER]):
        print("필수 환경 변수(Secrets)가 설정되지 않았습니다.")
        return

    try:
        video_path, caption, post_id = get_latest_reels_apify()
        
        if not video_path:
            print("분석할 신규 게시물이 없거나 수집에 실패했습니다.")
            return

        analysis_result = analyze_video_with_gemini(video_path, caption)
        
        message = f"📌 *[{TARGET_USER}] 최신 릴스 분석 보고서*\n\n{analysis_result}"
        send_telegram_message(message)
        
        save_processed_id(post_id)
        print("텔레그램 발송 완료 및 Post ID 저장 완료!")

    except Exception as e:
        error_msg = f"⚠️ 인스타 분석 중 오류 발생: {str(e)}"
        print(error_msg)
        send_telegram_message(error_msg)

if __name__ == "__main__":
    main()
