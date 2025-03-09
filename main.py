import os
import requests
import random
import time
import logging
import arabic_reshaper
import tempfile
import subprocess
from bidi.algorithm import get_display
from moviepy.editor import ImageClip, CompositeVideoClip, AudioFileClip
from PIL import Image, ImageDraw, ImageFont
from instabot import Bot
from gtts import gTTS

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG = {
    "hadith_api": "https://api.hadith.gading.dev/books/{book}?range={min}-{max}&lang=en",
    "books": ["bukhari", "muslim", "tirmidhi"],
    "fonts": {
        "arabic": "./fonts/NotoNaskhArabic-Regular.ttf",
        "english": "./fonts/Roboto-Regular.ttf"
    },
    "colors": {
        "background": (0, 0, 0),
        "arabic_text": (255, 255, 255),
        "translation_text": (255, 215, 0)
    },
    "video": {
        "size": (1080, 1920),  # Instagram Reel dimensions
        "fps": 24,
        "min_duration": 15,     # Minimum reel duration (seconds)
        "max_duration": 90      # Instagram's maximum duration
    },
    "max_retries": 3
}

def install_ffmpeg():
    """Ensure FFmpeg is installed"""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.info("Installing FFmpeg...")
        os.system("sudo apt-get update && sudo apt-get install -y ffmpeg")

def get_hadith():
    """Fetch random hadith from API"""
    for attempt in range(CONFIG["max_retries"]):
        try:
            book = random.choice(CONFIG["books"])
            response = requests.get(
                CONFIG["hadith_api"].format(book=book, min=1, max=300),
                headers={"User-Agent": "HadithReelsBot/1.0"},
                timeout=10
            )
            
            if response.status_code != 200:
                raise ValueError(f"HTTP {response.status_code}")
                
            data = response.json()
            
            if data.get("code") != 200:
                raise ValueError(f"API error {data.get('code')}")
                
            hadiths = data.get("data", {}).get("hadiths", [])
            if not hadiths:
                raise ValueError("No hadiths found")
                
            hadith = random.choice(hadiths)
            return {
                "arabic": hadith["arab"],
                "translation": hadith["en"],
                "book": data["data"]["name"],
                "number": hadith["number"]
            }
            
        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed: {str(e)}")
            time.sleep(2 ** attempt)
    
    logger.error("Failed to fetch hadith after retries")
    return None

def create_audio(text):
    """Generate TTS audio for translation"""
    try:
        tts = gTTS(text=text, lang="en")
        audio_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
        tts.save(audio_path)
        return audio_path
    except Exception as e:
        logger.error(f"Audio creation failed: {str(e)}")
        return None

def process_arabic_text(text):
    """Format Arabic text for proper display"""
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)

def create_hadith_image(hadith):
    """Generate visual content for the reel"""
    try:
        img = Image.new("RGB", CONFIG["video"]["size"], CONFIG["colors"]["background"])
        draw = ImageDraw.Draw(img)

        # Arabic text
        arabic_font = ImageFont.truetype(CONFIG["fonts"]["arabic"], 64)
        arabic_text = process_arabic_text(hadith["arabic"])
        draw.text((100, 300), arabic_text, font=arabic_font, fill=CONFIG["colors"]["arabic_text"])

        # English translation
        english_font = ImageFont.truetype(CONFIG["fonts"]["english"], 40)
        english_lines = []
        current_line = []
        for word in hadith["translation"].split():
            if draw.textlength(" ".join(current_line + [word]), font=english_font) < 900:
                current_line.append(word)
            else:
                english_lines.append(" ".join(current_line))
                current_line = [word]
        english_lines.append(" ".join(current_line))
        
        y_position = 1000
        for line in english_lines:
            draw.text((100, y_position), line, font=english_font, fill=CONFIG["colors"]["translation_text"])
            y_position += 50

        # Source attribution
        source_text = f"{hadith['book']} #{hadith['number']}"
        draw.text((100, 1800), source_text, font=english_font, fill=CONFIG["colors"]["translation_text"])

        image_path = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg").name
        img.save(image_path)
        return image_path

    except Exception as e:
        logger.error(f"Image creation failed: {str(e)}")
        return None

def create_video(hadith):
    """Combine audio and image into video"""
    audio_path = None
    image_path = None
    
    try:
        # Generate assets
        audio_path = create_audio(hadith["translation"])
        image_path = create_hadith_image(hadith)
        
        if not audio_path or not image_path:
            return None

        # Create video clip
        audio = AudioFileClip(audio_path)
        video = ImageClip(image_path).set_duration(audio.duration)
        video = video.set_audio(audio)
        
        # Enforce duration limits
        if video.duration > CONFIG["video"]["max_duration"]:
            video = video.subclip(0, CONFIG["video"]["max_duration"])
            
        output_path = "hadith_reel.mp4"
        video.write_videofile(
            output_path,
            fps=CONFIG["video"]["fps"],
            codec="libx264",
            audio_codec="aac",
            threads=4
        )
        return output_path
        
    finally:
        # Cleanup temporary files
        for path in [audio_path, image_path]:
            if path and os.path.exists(path):
                os.remove(path)

def post_to_instagram(video_path):
    """Upload video to Instagram"""
    try:
        bot = Bot()
        username = os.getenv("IG_USERNAME")
        password = os.getenv("IG_PASSWORD")
        
        # Session management
        session_file = f"{username}_uuid_and_cookie.json"
        if os.path.exists(session_file):
            bot.load_settings(session_file)
        else:
            bot.login(username=username, password=password, use_cookie=False)
            bot.save_settings(session_file)
        
        caption = f"Daily Hadith\n{hadith['book']} #{hadith['number']}\n#Hadith #Islam #Sunnah"
        bot.upload_video(video_path, caption=caption)
        return True
        
    except Exception as e:
        logger.error(f"Posting failed: {str(e)}")
        return False

def main():
    """Main execution flow"""
    install_ffmpeg()
    
    hadith = get_hadith()
    if not hadith:
        logger.error("No hadith obtained")
        return
        
    logger.info(f"Processing {hadith['book']} #{hadith['number']}")
    
    video_path = create_video(hadith)
    if not video_path or not os.path.exists(video_path):
        logger.error("Video creation failed")
        return
        
    logger.info("Video created successfully")
    
    if post_to_instagram(video_path):
        logger.info("Posted to Instagram")
    else:
        logger.error("Failed to post")
    
    # Cleanup final video
    if os.path.exists(video_path):
        os.remove(video_path)

if __name__ == "__main__":
    main()
