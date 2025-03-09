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
from chapters import CHAPTER_NAMES

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG = {
    "quran_api": "https://api.quran.com/api/v4/verses/by_page/{page}?translations=131&fields=text_uthmani,chapter_id,verse_number&per_page=7&mushaf=2",
    "audio_api": "https://everyayah.com/data/Alafasy_128kbps/{surah:03}{ayah:03}.mp3",
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
    },
    "api_retries": 5,
    "fallback_pages": [1, 2, 3, 4, 5, 600, 601, 602, 603, 604]
}

def install_ffmpeg():
    """Install FFmpeg if not available"""
    try:
        # Check if ffmpeg exists
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.info("Installing FFmpeg...")
        os.system("sudo apt-get update && sudo apt-get install -y ffmpeg")

def get_valid_page():
    """Generate valid page numbers with fallback"""
    try:
        page = random.randint(1, 604)
        test_url = CONFIG['quran_api'].format(page=page)
        response = requests.head(test_url, timeout=5)
        response.raise_for_status()
        return page
    except:
        return random.choice(CONFIG['fallback_pages'])

def get_verses_data():
    """Fetch verses with comprehensive validation"""
    for attempt in range(CONFIG['api_retries']):
        try:
            page = get_valid_page()
            logger.info(f"Attempt {attempt+1}: Using page {page}")
            
            response = requests.get(
                CONFIG['quran_api'].format(page=page),
                headers={"User-Agent": "IslamicReelsBot/1.0 (+https://github.com)"},
                timeout=10
            )
            
            if response.status_code == 404:
                raise ValueError(f"Invalid page {page}")
                
            response.raise_for_status()
            data = response.json()
            
            if 'verses' not in data or not isinstance(data['verses'], list):
                raise ValueError("Invalid API response format")
                
            verses = data['verses']
            random.shuffle(verses)
            
            collected = []
            total_duration = 0
            
            for verse in verses:
                chapter_id = verse.get('chapter_id')
                if not chapter_id or chapter_id not in CHAPTER_NAMES:
                    continue
                
                required_fields = ['text_uthmani', 'translations', 'verse_number']
                if not all(field in verse for field in required_fields):
                    continue
                
                verse_data = {
                    'arabic': verse['text_uthmani'],
                    'translation': verse['translations'][0]['text'],
                    'surah_en': CHAPTER_NAMES[chapter_id][0],
                    'surah_ar': CHAPTER_NAMES[chapter_id][1],
                    'surah_number': chapter_id,
                    'ayah_number': verse['verse_number'],
                    'audio': CONFIG['audio_api'].format(
                        surah=chapter_id,
                        ayah=verse['verse_number']
                    )
                }
                
                word_count = len(verse_data['arabic'].split())
                verse_data['duration'] = max(3, word_count * 0.4)
                
                if total_duration + verse_data['duration'] > CONFIG['video']['max_duration']:
                    break
                    
                collected.append(verse_data)
                total_duration += verse_data['duration']
                
                if total_duration >= CONFIG['video']['min_duration']:
                    break
                    
            if collected:
                logger.info(f"Collected {len(collected)} verses ({total_duration:.1f}s)")
                return collected
                
        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed: {str(e)}")
            time.sleep(2 ** attempt)
    
    logger.error("Failed to fetch verses after retries")
    return []

def download_audio(url):
    """Download audio with validation"""
    try:
        response = requests.head(url, timeout=5)
        response.raise_for_status()
        
        response = requests.get(url)
        response.raise_for_status()
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as f:
            f.write(response.content)
            return f.name
    except Exception as e:
        logger.error(f"Audio download failed: {str(e)}")
        return None

def process_arabic_text(text):
    """Format Arabic text for display"""
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)

def create_verse_image(verse, index, total):
    """Generate verse image with progress"""
    img = Image.new('RGB', CONFIG['video']['size'], CONFIG['colors']['background'])
    draw = ImageDraw.Draw(img)
    
    # Arabic text
    arabic_font = ImageFont.truetype(CONFIG['fonts']['arabic'], 80)
    arabic_text = process_arabic_text(f"{verse['arabic']}\n({verse['surah_ar']} {verse['ayah_number']})")
    draw.text((100, 300), arabic_text, font=arabic_font, fill=CONFIG['colors']['arabic_text'])
    
    # English translation
    english_font = ImageFont.truetype(CONFIG['fonts']['english'], 40)
    english_text = f"{verse['translation']}\n{verse['surah_en']} {verse['ayah_number']})"
    draw.text((100, 1000), english_text, font=english_font, fill=CONFIG['colors']['translation_text'])
    
    # Progress bar
    progress_width = 800
    draw.rectangle([(140, 1800), (140 + progress_width * (index/total), 1830)], fill=(255, 215, 0))
    
    temp_path = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False).name
    img.save(temp_path)
    return temp_path

def combine_audios(verses):
    """Concatenate audio files using FFmpeg"""
    temp_files = []
    try:
        # Download audio files
        for verse in verses:
            audio_path = download_audio(verse['audio'])
            if audio_path:
                verse['audio_path'] = audio_path
                temp_files.append(audio_path)
        
        # Create file list
        list_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
        for path in temp_files:
            list_file.write(f"file '{path}'\n")
        list_file.close()
        
        # Combine using FFmpeg with error checking
        output_path = "combined_audio.mp3"
        exit_code = os.system(f"ffmpeg -f concat -safe 0 -i {list_file.name} -c copy {output_path}")
        
        if exit_code != 0 or not os.path.exists(output_path):
            raise RuntimeError("FFmpeg failed to combine audio files")
            
        return output_path, temp_files + [list_file.name]
        
    except Exception as e:
        logger.error(f"Audio combining failed: {str(e)}")
        return None, []

def create_video(verses):
    """Create video from verses"""
    audio_path, temp_files = combine_audios(verses)
    if not audio_path:
        return None
        
    try:
        audio_clip = AudioFileClip(audio_path)
        total_duration = audio_clip.duration
        
        clips = []
        current_time = 0
        
        for idx, verse in enumerate(verses):
            img_path = create_verse_image(verse, idx+1, len(verses))
            clip_duration = min(verse.get('duration', 5), total_duration - current_time)
            
            clip = ImageClip(img_path).set_start(current_time).set_duration(clip_duration)
            clips.append(clip)
            current_time += clip_duration
            
            if current_time >= total_duration:
                break
        
        video = CompositeVideoClip(clips, size=CONFIG['video']['size'])
        video = video.set_audio(audio_clip)
        video = video.set_duration(total_duration)
        
        output_path = "final_reel.mp4"
        video.write_videofile(
            output_path,
            fps=CONFIG['video']['fps'],
            codec='libx264',
            audio_codec='aac',
            threads=4
        )
        return output_path
        
    finally:
        # Cleanup temporary files
        for f in [audio_path] + temp_files:
            if f and os.path.exists(f):
                os.remove(f)

def post_to_instagram(video_path):
    """Post video to Instagram"""
    try:
        bot = Bot()
        username = os.getenv('IG_USERNAME')
        password = os.getenv('IG_PASSWORD')
        
        session_file = f"{username}_uuid_and_cookie.json"
        if os.path.exists(session_file):
            bot.load_settings(session_file)
        else:
            bot.login(username=username, password=password, use_cookie=False)
            bot.save_settings(session_file)
        
        caption = f"Quranic Verses\n#Quran #Islam #DailyVerses"
        bot.upload_video(video_path, caption=caption)
        return True
    except Exception as e:
        logger.error(f"Posting failed: {str(e)}")
        return False

def main():
    """Main execution flow"""
    try:
        # Ensure FFmpeg is installed
        install_ffmpeg()
        
        verses = get_verses_data()
        if not verses:
            logger.error("No verses collected")
            return
            
        logger.info(f"Creating video with {len(verses)} verses")
        video_path = create_video(verses)
        
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
