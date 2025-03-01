import gradio as gr
import base64
import os
import shutil
import subprocess
import asyncio
import edge_tts
import pysrt
from google.colab import drive, files
import yt_dlp
from pydub import AudioSegment
from tqdm import tqdm
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential
import time

# نصب اولیه کتابخانه‌ها (فقط در Colab اجرا می‌شود)
def install_dependencies():
    subprocess.run(["pip", "install", "git+https://github.com/yaranbarzi/aigolden-audio-to-text.git"])
    subprocess.run(["pip", "install", "edge_tts", "yt-dlp", "pysrt", "rubberband-cli", "pydub", "google-generativeai", "tqdm", "tenacity", "gradio"])
    subprocess.run(["apt", "update"])
    subprocess.run(["apt", "install", "-y", "ffmpeg", "rubberband-cli"])

# اتصال به گوگل درایو
def mount_drive():
    drive.mount('/content/drive')
    return "Google Drive متصل شد."

# آپلود ویدیو
def upload_video(upload_method, yt_link, drive_path, local_file):
    if os.path.exists('input_video.mp4'):
        os.remove('input_video.mp4')
    if os.path.exists('audio.wav'):
        os.remove('audio.wav')
    if os.path.exists('audio.srt'):
        os.remove('audio.srt')
    if os.path.exists('dubbing_project'):
        shutil.rmtree('dubbing_project')

    if upload_method == "یوتیوب" and yt_link:
        video_opts = {'format': 'best', 'outtmpl': 'input_video.mp4'}
        audio_opts = {'format': 'bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'wav'}], 'outtmpl': 'audio'}
        with yt_dlp.YoutubeDL(video_opts) as ydl:
            ydl.download([yt_link])
        with yt_dlp.YoutubeDL(audio_opts) as ydl:
            ydl.download([yt_link])
        return "ویدیو و صوت از یوتیوب دانلود شد."
    elif upload_method == "گوگل درایو" and drive_path:
        subprocess.run(['cp', drive_path, 'input_video.mp4'])
        subprocess.run(['ffmpeg', '-i', 'input_video.mp4', '-vn', 'audio.wav'])
        return "ویدیو و صوت از گوگل درایو کپی شد."
    elif upload_method == "حافظه داخلی" and local_file:
        with open('input_video.mp4', 'wb') as f:
            f.write(local_file.read())
        subprocess.run(['ffmpeg', '-i', 'input_video.mp4', '-vn', 'audio.wav'])
        return "ویدیو آپلود و صوت استخراج شد."
    return "لطفاً ورودی معتبر ارائه دهید."

# استخراج متن
def extract_text(extraction_method, subtitle_file):
    if extraction_method == "Whisper":
        if os.path.exists('audio.wav'):
            subprocess.run(['whisper', 'audio.wav', '--model', 'large', '--output_dir', './', '--output_format', 'srt'])
            os.rename('audio.srt', 'audio.srt')
            return "متن با Whisper استخراج شد."
        return "فایل صوتی موجود نیست."
    elif subtitle_file:
        with open('audio.srt', 'wb') as f:
            f.write(subtitle_file.read())
        return "زیرنویس آپلود شد."
    return "لطفاً ورودی معتبر ارائه دهید."

# ترجمه زیرنویس
def translate_subtitles(translation_method, source_lang, target_lang, api_key, manual_subtitle):
    language_map = {"English (EN)": "English", "Persian (FA)": "فارسی", "German (DE)": "German", "French (FR)": "French", "Italian (IT)": "Italian", "Spanish (ES)": "Spanish", "Chinese (ZH)": "Chinese", "Korean (KO)": "Korean", "Russian (RU)": "Russian", "Arabic (AR)": "Arabic", "Japanese (JA)": "Japanese"}
    target_lang_name = language_map.get(target_lang, "English")

    if translation_method == "هوش مصنوعی":
        if not api_key:
            return "لطفاً کلید API را وارد کنید."
        genai.configure(api_key=api_key)
        subs = pysrt.open('/content/audio.srt')

        @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
        def translate(text):
            model = genai.GenerativeModel('gemini-1.5-flash')
            prompt = f"Translate the following text to {target_lang_name} with appropriate punctuation:\n{text}" if target_lang != "Persian (FA)" else f"متن را به فارسی عامیانه با نقطه و کاما ترجمه کن:\n{text}"
            response = model.generate_content(prompt)
            time.sleep(3)
            return response.text

        for sub in tqdm(subs, desc="ترجمه"):
            sub.text = translate(sub.text)
        subs.save('/content/audio_translated.srt', encoding='utf-8')
        os.rename('/content/audio_translated.srt', 'audio_fa.srt')
        return f"ترجمه به {target_lang} انجام شد."
    elif manual_subtitle:
        with open('audio_fa.srt', 'wb') as f:
            f.write(manual_subtitle.read())
        return "زیرنویس ترجمه‌شده آپلود شد."
    return "لطفاً ورودی معتبر ارائه دهید."

# ساخت سگمنت‌های صوتی
async def generate_segments(voice_choice):
    VOICE_MAP = {"فرید (FA)": "fa-IR-FaridNeural", "دلارا (FA)": "fa-IR-DilaraNeural", "Jenny (EN)": "en-US-JennyNeural", "Guy (EN)": "en-US-GuyNeural", "Katja (DE)": "de-DE-KatjaNeural", "Conrad (DE)": "de-DE-ConradNeural", "Elvira (ES)": "es-ES-ElviraNeural", "Alvaro (ES)": "es-ES-AlvaroNeural", "Denise (FR)": "fr-FR-DeniseNeural", "Henri (FR)": "fr-FR-HenriNeural", "Nanami (JA)": "ja-JP-NanamiNeural", "Keita (JA)": "ja-JP-KeitaNeural", "SunHi (KO)": "ko-KR-SunHiNeural", "InJoon (KO)": "ko-KR-InJoonNeural", "Xiaoxiao (ZH)": "zh-CN-XiaoxiaoNeural", "Yunyang (ZH)": "zh-CN-YunyangNeural", "Svetlana (RU)": "ru-RU-SvetlanaNeural", "Dmitry (RU)": "ru-RU-DmitryNeural", "Amina (AR)": "ar-EG-AminaNeural", "Hamed (AR)": "ar-EG-HamedNeural", "Isabella (IT)": "it-IT-IsabellaNeural", "Diego (IT)": "it-IT-DiegoNeural"}
    os.makedirs('dubbing_project/dubbed_segments', exist_ok=True)
    subs = pysrt.open('/content/audio_fa.srt')
    selected_voice = VOICE_MAP.get(voice_choice, "fa-IR-FaridNeural")

    for i, sub in enumerate(subs):
        start_time = sub.start.seconds + sub.start.milliseconds / 1000
        end_time = sub.end.seconds + sub.end.milliseconds / 1000
        target_duration = end_time - start_time
        communicate = edge_tts.Communicate(sub.text, selected_voice)
        await communicate.save(f"dubbing_project/dubbed_segments/temp_{i+1}.mp3")
        subprocess.run(['ffmpeg', '-i', f"dubbing_project/dubbed_segments/temp_{i+1}.mp3", '-y', f"dubbing_project/dubbed_segments/temp_wav_{i+1}.wav"])
        duration = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', f"dubbing_project/dubbed_segments/temp_wav_{i+1}.wav"], capture_output=True, text=True).stdout.strip())
        speed_factor = duration / target_duration
        subprocess.run(['ffmpeg', '-i', f"dubbing_project/dubbed_segments/temp_wav_{i+1}.wav", '-filter:a', f'rubberband=tempo={speed_factor}', '-y', f"dubbing_project/dubbed_segments/dub_{i+1}.wav"])
        os.remove(f"dubbing_project/dubbed_segments/temp_{i+1}.mp3")
        os.remove(f"dubbing_project/dubbed_segments/temp_wav_{i+1}.wav")
    return f"سگمنت‌ها با صدای {voice_choice} ساخته شد."

def run_generate_segments(voice_choice):
    asyncio.run(generate_segments(voice_choice))
    return f"سگمنت‌ها با صدای {voice_choice} ساخته شد."

# ترکیب ویدیو و صدا
def combine_video_audio(keep_original_audio, original_audio_volume):
    subs = pysrt.open('/content/audio_fa.srt')
    filter_complex = f"[0:a]volume={original_audio_volume if keep_original_audio else 0}[original_audio];"
    valid_segments = []
    for i, sub in enumerate(subs):
        start_time_ms = (sub.start.hours * 3600 + sub.start.minutes * 60 + sub.start.seconds) * 1000 + sub.start.milliseconds
        filter_complex += f"[{i+1}:a]adelay={start_time_ms}|{start_time_ms}[a{i+1}];"
        valid_segments.append(i)
    merge_command = "[original_audio]" + "".join(f"[a{i+1}]" for i in valid_segments) + f"amix=inputs={len(valid_segments) + 1}:normalize=0[aout]"
    filter_complex += merge_command
    input_files = " ".join([f"-i dubbing_project/dubbed_segments/dub_{i+1}.wav" for i in valid_segments])
    output_filename = 'final_dubbed_video_FA.mp4'
    subprocess.run(f'ffmpeg -y -i input_video.mp4 {input_files} -filter_complex "{filter_complex}" -map 0:v -map "[aout]" -c:v copy {output_filename}', shell=True)
    return output_filename, "ویدیو نهایی ساخته شد."

# رابط کاربری Gradio
with gr.Blocks() as demo:
    gr.Markdown("# ابزار دوبله ویدیو با هوش مصنوعی")
    
    with gr.Tab("نصب و اتصال"):
        gr.Button("نصب کتابخانه‌ها").click(fn=install_dependencies, outputs=gr.Textbox(label="وضعیت نصب"))
        gr.Button("اتصال به گوگل درایو").click(fn=mount_drive, outputs=gr.Textbox(label="وضعیت اتصال"))
    
    with gr.Tab("آپلود ویدیو"):
        upload_method = gr.Dropdown(["یوتیوب", "گوگل درایو", "حافظه داخلی"], label="روش آپلود")
        yt_link = gr.Textbox(label="لینک یوتیوب")
        drive_path = gr.Textbox(label="مسیر گوگل درایو")
        local_file = gr.File(label="فایل ویدیویی")
        gr.Button("آپلود").click(fn=upload_video, inputs=[upload_method, yt_link, drive_path, local_file], outputs=gr.Textbox(label="وضعیت"))

    with gr.Tab("استخراج متن"):
        extraction_method = gr.Dropdown(["Whisper", "آپلود زیرنویس"], label="روش استخراج")
        subtitle_file = gr.File(label="فایل زیرنویس")
        gr.Button("استخراج").click(fn=extract_text, inputs=[extraction_method, subtitle_file], outputs=gr.Textbox(label="وضعیت"))

    with gr.Tab("ترجمه زیرنویس"):
        translation_method = gr.Dropdown(["هوش مصنوعی", "آپلود زیرنویس بصورت دستی"], label="روش ترجمه")
        source_lang = gr.Dropdown(["English (EN)", "Persian (FA)", "German (DE)", "French (FR)", "Italian (IT)", "Spanish (ES)", "Chinese (ZH)", "Korean (KO)", "Russian (RU)", "Arabic (AR)", "Japanese (JA)"], label="زبان مبدا")
        target_lang = gr.Dropdown(["Persian (FA)", "English (EN)", "German (DE)", "French (FR)", "Italian (IT)", "Spanish (ES)", "Chinese (ZH)", "Korean (KO)", "Russian (RU)", "Arabic (AR)", "Japanese (JA)"], label="زبان مقصد")
        api_key = gr.Textbox(label="کلید API (برای هوش مصنوعی)", type="password")
        manual_subtitle = gr.File(label="فایل زیرنویس ترجمه‌شده")
        gr.Button("ترجمه").click(fn=translate_subtitles, inputs=[translation_method, source_lang, target_lang, api_key, manual_subtitle], outputs=gr.Textbox(label="وضعیت"))

    with gr.Tab("ساخت سگمنت‌های صوتی"):
        voice_choice = gr.Dropdown(list(VOICE_MAP.keys()), label="انتخاب صدا")
        gr.Button("ساخت سگمنت‌ها").click(fn=run_generate_segments, inputs=voice_choice, outputs=gr.Textbox(label="وضعیت"))

    with gr.Tab("ترکیب ویدیو و صدا"):
        keep_original_audio = gr.Checkbox(label="حفظ صدای اصلی")
        original_audio_volume = gr.Slider(0, 1, value=0.05, step=0.005, label="میزان صدای اصلی")
        gr.Button("ترکیب").click(fn=combine_video_audio, inputs=[keep_original_audio, original_audio_volume], outputs=[gr.Video(label="ویدیوی نهایی"), gr.Textbox(label="وضعیت")])

demo.launch()
