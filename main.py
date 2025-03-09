import os
import requests
import random
import time
import logging
import arabic_reshaper
import tempfile
import subprocess
from bidi.algorithm import get_display
from moviepy.editor import ImageClip, CompositeVideoClip, AudioFileClip, concatenate_audioclips
from PIL import Image, ImageDraw, ImageFont
from instabot import Bot
from gtts import gTTS

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG = {
    "hadith_api": "https://api.hadith.gading.dev/books/{book}/range/{min}-{max}",
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
        "size": (1080, 1920),
        "fps": 24,
        "min_duration": 30,
        "max_duration": 90
    }
}

def install_ffmpeg():
    """Install FFmpeg if missing"""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.info("Installing FFmpeg...")
        os.system("sudo apt-get update && sudo apt-get install -y ffmpeg")

def get_hadith():
    """Fetch random hadith with translation"""
    try:
        book = random.choice(CONFIG["books"])
        response = requests.get(
            CONFIG["hadith_api"].format(
                book=book,
                min=1,
                max=200  # Adjust based on actual hadith count per book
            )
        )
        data = response.json()
        
        if data["code"] != 200 or not data["data"]["hadiths"]:
            raise ValueError("Invalid API response")
            
        hadith = random.choice(data["data"]["hadiths"])
        return {
            "arabic": hadith["arabic"],
            "translation": hadith["english"],
            "book": data["data"]["name"],
            "number": hadith["number"]
        }
        
    except Exception as e:
        logger.error(f"Hadith API Error: {str(e)}")
        raise

def create_audio(text, lang="en"):
    """Generate TTS audio"""
    try:
        tts = gTTS(text=text, lang=lang)
        audio_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
        tts.save(audio_path)
        return audio_path
    except Exception as e:
        logger.error(f"Audio generation failed: {str(e)}")
        return None

def process_arabic_text(text):
    """Format Arabic text for display"""
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)

def create_hadith_image(hadith):
    """Generate hadith image"""
    img = Image.new('RGB', CONFIG['video']['size'], CONFIG['colors']['background'])
    draw = ImageDraw.Draw(img)
    
    # Arabic text
    arabic_font = ImageFont.truetype(CONFIG['fonts']['arabic'], 60)
    arabic_text = process_arabic_text(hadith["arabic"])
    draw.text((100, 300), arabic_text, font=arabic_font, fill=CONFIG['colors']['arabic_text'])
    
    # English translation
    english_font = ImageFont.truetype(CONFIG['fonts']['english'], 40)
    english_text = f"{hadith['translation']}\n\n- {hadith['book']} {hadith['number']}"
    draw.text((100, 1000), english_text, font=english_font, fill=CONFIG['colors']['translation_text'])
    
    temp_path = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False).name
    img.save(temp_path)
    return temp_path

def create_video(hadith):
    """Create video with audio"""
    try:
        # Generate audio
        audio_path = create_audio(hadith["translation"])
        if not audio_path:
            return None
            
        # Create image
        image_path = create_hadith_image(hadith)
        
        # Create video clip
        audio_clip = AudioFileClip(audio_path)
        video_clip = ImageClip(image_path).set_duration(audio_clip.duration)
        
        # Combine audio and video
        final_clip = video_clip.set_audio(audio_clip)
        
        # Enforce duration limits
        if final_clip.duration > CONFIG['video']['max_duration']:
            final_clip = final_clip.subclip(0, CONFIG['video']['max_duration'])
            
        output_path = "hadith_reel.mp4"
        final_clip.write_videofile(
            output_path,
            fps=CONFIG['video']['fps'],
            codec='libx264'
        )
        return output_path
        
    finally:
        for f in [audio_path, image_path]:
            if os.path.exists(f):
                os.remove(f)

def post_to_instagram(video_path):
    """Post video to Instagram"""
    try:
        bot = Bot()
        username = os.getenv('IG_USERNAME')
        password = os.getenv('IG_PASSWORD')
        
        # Session management
        session_file = f"{username}_uuid_and_cookie.json"
        if os.path.exists(session_file):
            bot.load_settings(session_file)
        else:
            bot.login(username=username, password=password, use_cookie=False)
            bot.save_settings(session_file)
        
        caption = f"Daily Hadith\n#Hadith #Islam #Sunnah"
        bot.upload_video(video_path, caption=caption)
        return True
    except Exception as e:
        logger.error(f"Posting failed: {str(e)}")
        return False

def main():
    """Main execution flow"""
    try:
        install_ffmpeg()
        
        hadith = get_hadith()
        logger.info(f"Processing {hadith['book']} {hadith['number']}")
        
        video_path = create_video(hadith)
        if video_path and os.path.exists(video_path):
            logger.info("Video created successfully")
            if post_to_instagram(video_path):
                logger.info("Posted to Instagram")
            else:
                logger.error("Failed to post")
        else:
            logger.error("Video creation failed")
            
    except Exception as e:
        logger.error(f"Critical error: {str(e)}")

if __name__ == "__main__":
    main()
