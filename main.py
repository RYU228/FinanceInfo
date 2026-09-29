import os
import glob
import requests
import yt_dlp
from google import genai

# 환경 변수 로드
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
INSTA_SESSION_ID = os.environ.get("INSTA_SESSION_ID")
TARGET_USER = os.environ.get("TARGET_INSTA_USER")

LAST_POST_FILE = "last_post.txt"

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

def get_last_processed_id():
    """이전에 처리한 게시물 ID 읽기"""
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""

def save_processed_id(post_id):
    """최신 처리한 게시물 ID 저장"""
    with open(LAST_POST_FILE, "w", encoding="utf-8") as f:
        f.write(post_id)

def download_latest_reels_ytdlp():
    target_url = f"https://www.instagram.com/{TARGET_USER}/reels/"
    output_dir = "downloads"
    os.makedirs(output_dir, exist_ok=True)
    
    ydl_opts = {
        'outtmpl': f'{output_dir}/%(id)s.%(ext)s',
        'playlistend': 1,  # 가장 최근 릴스 1개만
        'quiet': True,
        'no_warnings': True,
    }

    if INSTA_SESSION_ID:
        ydl_opts['http_headers'] = {
            'Cookie': f'sessionid={INSTA_SESSION_ID};'
        }

    print(f"[{TARGET_USER}] 최신 릴스 수집 중 (yt-dlp)...")
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(target_url, download=False)  # 먼저 정보만 조회
            
            if 'entries' in info and len(info['entries']) > 0:
                entry = info['entries'][0]
            else:
                entry = info

            current_post_id = str(entry.get('id', ''))
            last_post_id = get_last_processed_id()

            # 이전 ID와 동일하면 중복 처리 건너뛰기
            if current_post_id and current_post_id == last_post_id:
                print(f"이미 처리된 게시물입니다. (Post ID: {current_post_id})")
                return None, None, None

            # 새로운 게시물이면 다운로드 진행
            ydl.download([entry.get('webpage_url', target_url)])
            caption = entry.get('description', '') or entry.get('title', '')
            
            video_files = glob.glob(f"{output_dir}/*.mp4")
            if video_files:
                return video_files[0], caption, current_post_id

        except Exception as e:
            print(f"yt-dlp 처리 중 에러: {e}")
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
    if not all([GEMINI_API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TARGET_USER]):
        print("필수 환경 변수(Secrets)가 설정되지 않았습니다.")
        return

    try:
        video_path, caption, post_id = download_latest_reels_ytdlp()
        
        if not video_path:
            print("분석할 신규 게시물이 없거나 다운로드에 실패했습니다.")
            return

        analysis_result = analyze_video_with_gemini(video_path, caption)
        
        message = f"📌 *[{TARGET_USER}] 최신 릴스 분석 보고서*\n\n{analysis_result}"
        send_telegram_message(message)
        
        # 분석 성공 시 최신 Post ID 저장
        save_processed_id(post_id)
        print("텔레그램 발송 완료 및 Post ID 저장 완료!")

    except Exception as e:
        error_msg = f"⚠️ 인스타 분석 중 오류 발생: {str(e)}"
        print(error_msg)
        send_telegram_message(error_msg)

if __name__ == "__main__":
    main()
