import threading
import queue
from openai import OpenAI
import time
import numpy as np
import soundfile as sf
import io
import sounddevice as sd
from collections import deque
import difflib
from deep_translator import GoogleTranslator
from gtts import gTTS
import os
import pygame
import shutil
import dotenv
import argparse
import sys

# Validators
# testing automatic trigger for jenkins
#memory test
def restricted_float(x):
    try:
        x = float(x)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{x} is not a floating-point number")
    if x < 0.001 or x > 1.0:
        raise argparse.ArgumentTypeError(f"{x} is out of range [0.001, 1.0]")
    return x

def restricted_int(x):
    try:
        x = int(x)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{x} is not an integer")
    if x < 2:
        raise argparse.ArgumentTypeError(f"{x} is too small; minimum queue size is 2")
    return x

def restricted_language(value):
    allowed_langs = {"zh": "Mandarin", "hi": "Hindi", "es": "Spanish", "fr": "French", "de": "German"}
    code = value.lower().strip()
    if code not in allowed_langs:
        options = ", ".join([f"'{k}' ({v})" for k, v in allowed_langs.items()])
        raise argparse.ArgumentTypeError(f"'{value}' not allowed. Choose from: {options}")
    return code

def restricted_bool(x):
    if isinstance(x, bool): return x
    if x.lower() in ('yes', 'true', 't', 'y', '1'): return True
    if x.lower() in ('no', 'false', 'f', 'n', '0'): return False
    raise argparse.ArgumentTypeError('Boolean value expected.')


parser = argparse.ArgumentParser(description="Stefie: Real-time Speech-to-Speech Translator")
parser.add_argument("-l", "--lang", type=restricted_language, default="de")
parser.add_argument("-s", "--silence", type=restricted_float, default=0.02)
parser.add_argument("-cS", "--chunk_size", type=int, default=1024)
parser.add_argument("-SR", "--sample_rate", type=int, default=16000)
parser.add_argument("-w", "--window", type=float, default=3.0)
parser.add_argument("-q", "--queue_size", type=restricted_int, default=10)
parser.add_argument("-save", "--save", type=restricted_bool, default=False)

args = parser.parse_args()


dotenv.load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("Error: OPENAI_API_KEY missing.")
    sys.exit(1)

audio_queue = queue.Queue(maxsize=args.queue_size)
transcript_queue = queue.Queue()
tts_queue = queue.Queue()
save_queue = queue.Queue()

samplerate = args.sample_rate
audio_buffer = deque(maxlen=60 * samplerate)
look_up_text = ""
client = OpenAI(api_key=api_key, timeout=60)

pause_event, stop_event = threading.Event(), threading.Event()
pause_event.set()

# Main

def audio_stream():
    def callback(indata, frames, time_info, status):
        audio_buffer.extend(indata[:, 0])
    try:
        with sd.InputStream(callback=callback, samplerate=samplerate, channels=1, 
                          dtype="float32", blocksize=args.chunk_size):
            print(f"Recording (Target: {args.lang.upper()})")
            while not stop_event.is_set():
                pause_event.wait()
                time.sleep(0.1)
    except Exception as e:
        print(f"Stream error: {e}"); stop_event.set()

def keyboard_listener():
    print("Commands: [p] Pause/Resume | [q] Quit")
    while not stop_event.is_set():
        key = input().strip().lower()
        if key == "p":
            if pause_event.is_set(): pause_event.clear(); print("PAUSED")
            else: pause_event.set(); print("RESUMED")
        elif key == "q": print("Shutting down..."); stop_event.set()
except EOFError:
    #If in jenkins, input fails immediately
    #we wait so the thread doesn't crash of loop infinitely
    time.sleep(1)
    continue
def clean_transcripts(new_text: str, min_overlap_words=3):
    global look_up_text
    import string
    new_text_processed = new_text.translate(str.maketrans("", "", string.punctuation)).lower()
    prev = look_up_text[-1000:] if len(look_up_text) >= 1000 else look_up_text
    if prev:
        seq = difflib.SequenceMatcher(None, prev.split(), new_text_processed.split())
        match = seq.find_longest_match(0, len(prev.split()), 0, len(new_text_processed.split()))
        if match.size >= min_overlap_words:
            new_text_processed = " ".join(new_text_processed.split()[match.b + match.size:])
    look_up_text = (look_up_text + " " + new_text_processed.strip()).strip()
    return new_text_processed

def slice_audio():
    diff_aud_buff = 10 * samplerate 
    while not stop_event.is_set():
        pause_event.wait()
        time.sleep(5) 
        if len(audio_buffer) >= args.window * samplerate:
            recent = np.array(list(audio_buffer)[-diff_aud_buff:], dtype=np.float32)
            if np.max(np.abs(recent)) < args.silence: continue
            try: audio_queue.put(recent, timeout=1)
            except queue.Full: pass

def whisper_worker():
    while not stop_event.is_set():
        try: audio = audio_queue.get(timeout=1)
        except queue.Empty: continue
        wav_buf = io.BytesIO()
        sf.write(wav_buf, audio, samplerate, format='WAV', subtype='PCM_16')
        wav_buf.seek(0)
        try:
            res = client.audio.transcriptions.create(model="whisper-1", file=("slice.wav", wav_buf), language="en")
            cleaned = clean_transcripts(res.text)
            if cleaned.strip():
                transcript_queue.put(cleaned)
        except Exception as e: print(f"Whisper Error: {e}")
        finally: audio_queue.task_done()

def translate_worker():
    while not stop_event.is_set():
        try: en_text = transcript_queue.get(timeout=1)
        except queue.Empty: continue
        try:
            target_text = GoogleTranslator(source='auto', target=args.lang).translate(en_text)
            print(f"Translated ({args.lang}): {target_text}")
            tts_queue.put((target_text, args.lang, en_text)) 
        except Exception as e: print(f"Translation error: {e}")
        finally: transcript_queue.task_done()

def tts_worker():
    pygame.mixer.init()
    while not stop_event.is_set():
        try: text, lang, orig_en = tts_queue.get(timeout=1)
        except queue.Empty: continue
        try:
            mp3_fp = io.BytesIO()
            gTTS(text, lang=lang).write_to_fp(mp3_fp)
            mp3_fp.seek(0)
            
            if args.save:
                save_queue.put(("data", orig_en, text, mp3_fp.getvalue()))

            pygame.mixer.music.load(mp3_fp, "mp3")
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy(): time.sleep(0.1)
        except Exception as e: print(f"TTS Error: {e}")
        finally: tts_queue.task_done()

def local_saver():
    if not args.save: return
    sess_id = int(time.time())
    sess_path = f"session_{sess_id}"
    os.makedirs(os.path.join(sess_path, "translated_audio"), exist_ok=True)
    log_file = os.path.join(sess_path, "log.txt")
    item_count = 0

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"Session: {time.ctime()}\n" + "-"*20 + "\n")
        while not stop_event.is_set() or not save_queue.empty():
            try:
                _, en, tr, audio_bytes = save_queue.get(timeout=1)
                item_count += 1
                audio_filename = f"target_{item_count}.mp3"
                with open(os.path.join(sess_path, "translated_audio", audio_filename), "wb") as ab:
                    ab.write(audio_bytes)
                
                ts = time.strftime("%H:%M:%S")
                f.write(f"[{ts}] EN: {en}\n[{ts}] {args.lang.upper()}: {tr}\n[{ts}] FILE: {audio_filename}\n\n")
                f.flush()
                save_queue.task_done()
            except queue.Empty: continue
    
    # Archive the session
    print(f"Archiving session to {sess_path}.zip...")
    shutil.make_archive(sess_path, 'zip', sess_path)
    shutil.rmtree(sess_path)
    print("Session archived and cleaned.")

def main():
    funcs = [audio_stream, slice_audio, whisper_worker, keyboard_listener, translate_worker, tts_worker, local_saver]
    threads = [threading.Thread(target=f, daemon=True) for f in funcs]
    for t in threads: t.start()
    try:
        while not stop_event.is_set(): time.sleep(1)
    except KeyboardInterrupt: stop_event.set()

if __name__ == "__main__":
    main()