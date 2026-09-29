import os
import glob
import datetime
import requests
import instaloader
from google import genai

# 1. GitHub Secrets 환경 변수 로드
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
INSTA_SESSION_ID = os.environ.get("INSTA_SESSION_ID")
TARGET_USER = os.environ.get("TARGET_INSTA_USER")

def send_telegram_message(message):
    """텔레그램 메시지 발송 함수"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, json=payload)
    return response.json()

def download_latest_reels():
    """최신 인스타 릴스 다운로드"""
    L = instaloader.Instaloader(
        download_pictures=False,
        download_videos=True,
        download_video_thumbnails=False,
        save_metadata=False,
        max_connection_attempts=1  # 429 차단 시 긴 재시도 대기 없이 즉시 종료
    )
    
    # 쿠키 세션 설정 (차단 방지)
    if INSTA_SESSION_ID:
        L.context._session.cookies.set('sessionid', INSTA_SESSION_ID, domain='.instagram.com')

    print(f"[{TARGET_USER}] 계정 최신 게시글 확인 중...")
    profile = instaloader.Profile.from_username(L.context, TARGET_USER)
    
    posts = profile.get_posts()
    latest_post = next(posts, None)
    
    if not latest_post:
        print("게시글을 찾을 수 없습니다.")
        return None, None

    if not latest_post.is_video:
        print("최신 게시글이 영상(릴스)이 아닙니다.")
        return None, None

    # 최근 24시간 이내 작성 여부 검증
    now = datetime.datetime.now(datetime.timezone.utc)
    post_date = latest_post.date_utc.replace(tzinfo=datetime.timezone.utc)
    
    if (now - post_date).total_seconds() > 86400:
        print("최신 글이 24시간 이전에 올라온 글입니다. 분석을 건너끠니다.")
        return None, None

    target_dir = "downloads"
    L.download_post(latest_post, target=target_dir)
    
    video_files = glob.glob(f"{target_dir}/*.mp4")
    if video_files:
        return video_files[0], latest_post.caption
    
    return None, None

def analyze_video_with_gemini(video_path, caption):
    """Gemini API를 사용한 영상 및 본문 분석"""
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
    
    # 업로드한 임시 파일 삭제
    client.files.delete(name=video_file.name)
    
    return response.text

def main():
    # 어떤 환경변수가 누락되었는지 출력
    missing_vars = []
    if not GEMINI_API_KEY: missing_vars.append("GEMINI_API_KEY")
    if not TELEGRAM_BOT_TOKEN: missing_vars.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID: missing_vars.append("TELEGRAM_CHAT_ID")
    if not TARGET_USER: missing_vars.append("TARGET_INSTA_USER")

    if missing_vars:
        print(f"누락된 필수 환경 변수: {', '.join(missing_vars)}")
        return

    try:
        video_path, caption = download_latest_reels()
        
        if not video_path:
            print("분석 대상 신규 영상이 없습니다.")
            return

        analysis_result = analyze_video_with_gemini(video_path, caption)
        
        message = f"📌 *[{TARGET_USER}] 최신 릴스 분석 보고서*\n\n{analysis_result}"
        send_telegram_message(message)
        print("성공적으로 텔레그램 메시지를 발송했습니다.")

    except Exception as e:
        error_msg = f"⚠️ 인스타 분석 중 오류 발생: {str(e)}"
        print(error_msg)
        send_telegram_message(error_msg)

if __name__ == "__main__":
    main()
