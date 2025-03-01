import gradio as gr
import os
import subprocess
import pysrt
import edge_tts
import asyncio
import yt_dlp
import shutil
import google.generativeai as genai
from tqdm.notebook import tqdm
import time
from tenacity import retry, stop_after_attempt, wait_exponential

# تنظیمات اولیه
os.makedirs('dubbing_project/dubbed_segments', exist_ok=True)

# تعریف گوینده‌ها
VOICE_MAP = {
    "فرید (FA)": "fa-IR-FaridNeural",
    "دلارا (FA)": "fa-IR-DilaraNeural",
    "Jenny (EN)": "en-US-JennyNeural",
    "Guy (EN)": "en-US-GuyNeural",
    "Katja (DE)": "de-DE-KatjaNeural",
    "Conrad (DE)": "de-DE-ConradNeural",
    "Denise (FR)": "fr-FR-DeniseNeural",
    "Henri (FR)": "fr-FR-HenriNeural",
    "Isabella (IT)": "it-IT-IsabellaNeural",
    "Diego (IT)": "it-IT-DiegoNeural",
    "Elvira (ES)": "es-ES-ElviraNeural",
    "Alvaro (ES)": "es-ES-AlvaroNeural",
    "Xiaoxiao (ZH)": "zh-CN-XiaoxiaoNeural",
    "Yunyang (ZH)": "zh-CN-YunyangNeural",
    "SunHi (KO)": "ko-KR-SunHiNeural",
    "InJoon (KO)": "ko-KR-InJoonNeural",
    "Svetlana (RU)": "ru-RU-SvetlanaNeural",
    "Dmitry (RU)": "ru-RU-DmitryNeural",
    "Amina (AR)": "ar-EG-AminaNeural",
    "Hamed (AR)": "ar-EG-HamedNeural",
    "Nanami (JA)": "ja-JP-NanamiNeural",
    "Keita (JA)": "ja-JP-KeitaNeural"
}

# تابع برای دانلود ویدیو از یوتیوب
def download_video(url):
    if url.strip():
        video_opts = {
            'format': 'best',
            'outtmpl': 'input_video.mp4'
        }
        with yt_dlp.YoutubeDL(video_opts) as ydl:
            ydl.download([url])
        return True
    return False

# تابع برای استخراج متن از فایل صوتی
def extract_text(audio_file):
    if audio_file:
        subprocess.run(['whisper', audio_file, '--model', 'large', '--output_dir', './', '--output_format', 'srt'])
        return "audio.srt"
    return None

# تابع برای ترجمه متن
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def translate_text(text, source_lang, target_lang):
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"Translate this text from {source_lang} to {target_lang}: {text}"
    response = model.generate_content(prompt)
    return response.text

# تابع برای ترجمه زیرنویس
def translate_subtitle(subtitle_file, api_key, source_lang, target_lang):
    if api_key:
        genai.configure(api_key=api_key)
        subs = pysrt.open(subtitle_file)
        for sub in subs:
            sub.text = translate_text(sub.text, source_lang, target_lang)
        subs.save('audio_fa.srt', encoding='utf-8')
        return "audio_fa.srt"
    return None

# تابع برای تولید صدا
async def generate_speech(subtitle_file, voice_choice):
    subs = pysrt.open(subtitle_file)
    selected_voice = VOICE_MAP.get(voice_choice)
    for i, sub in enumerate(subs):
        communicate = edge_tts.Communicate(sub.text, selected_voice)
        await communicate.save(f"dubbing_project/dubbed_segments/dub_{i+1}.mp3")
    return "dubbing_project/dubbed_segments/"

# تابع اصلی برای اجرای کل فرآیند
def run_dubbing(upload_method, yt_link, drive_path, api_key, voice_choice, keep_original_audio, original_audio_volume):
    # آپلود ویدیو
    if upload_method == "یوتیوب" and yt_link.strip():
        download_video(yt_link)
    elif upload_method == "گوگل درایو" and drive_path.strip():
        shutil.copy(drive_path, 'input_video.mp4')
    elif upload_method == "حافظه داخلی":
        # این بخش نیاز به آپلود فایل از طریق Gradio دارد
        pass
    
    # استخراج صدا از ویدیو
    subprocess.run(['ffmpeg', '-i', 'input_video.mp4', '-vn', 'audio.wav'])
    
    # استخراج متن
    subtitle_file = extract_text("audio.wav")
    
    # ترجمه متن
    translated_subtitle = translate_subtitle(subtitle_file, api_key, "English", "Persian")
    
    # تولید صدا
    asyncio.run(generate_speech(translated_subtitle, voice_choice))
    
    # ترکیب صدا و ویدیو
    if keep_original_audio:
        subprocess.run(['ffmpeg', '-i', 'input_video.mp4', '-i', 'dubbing_project/dubbed_segments/dub_1.wav', '-filter_complex', f'[0:a]volume={original_audio_volume}[a0];[1:a]volume=1.0[a1];[a0][a1]amix=inputs=2:duration=longest', '-c:v', 'copy', 'output_video.mp4'])
    else:
        subprocess.run(['ffmpeg', '-i', 'input_video.mp4', '-i', 'dubbing_project/dubbed_segments/dub_1.wav', '-map', '0:v', '-map', '1:a', '-c:v', 'copy', 'output_video.mp4'])
    
    return "ویدیو با موفقیت دوبله شد!"

# ایجاد رابط کاربری Gradio
interface = gr.Interface(
    fn=run_dubbing,
    inputs=[
        gr.Dropdown(label="روش آپلود ویدیو", choices=["یوتیوب", "گوگل درایو", "حافظه داخلی"]),
        gr.Textbox(label="لینک ویدیو یوتیوب"),
        gr.Textbox(label="مسیر فایل در گوگل درایو"),
        gr.Textbox(label="کلید API گوگل"),
        gr.Dropdown(label="انتخاب گوینده", choices=list(VOICE_MAP.keys())),
        gr.Checkbox(label="حفظ صدای اصلی ویدیو"),
        gr.Slider(label="میزان صدای اصلی", minimum=0, maximum=1, step=0.01, value=0.05)
    ],
    outputs="text",
    title="ابزار دوبله ویدیو",
    description="این ابزار به شما امکان می‌دهد ویدیوهای یوتیوب را دوبله کنید."
)

# اجرای رابط کاربری
interface.launch(share=True)
