# Real-Time Audio Transcription, Translation & TTS Pipeline

This project is a real-time audio processing pipeline that captures microphone input, transcribes speech using OpenAI’s transcription API, removes overlapping text between audio windows, translates the transcription into another language, and plays back the translated speech using text-to-speech.

It is designed as a **multi-threaded streaming system** with pause/resume support and modular workers for each stage of the pipeline.

---

## Features

* Live microphone audio capture
* Speech-to-text using OpenAI (`gpt-4o-transcribe`)
* Automatic removal of overlapping transcript segments
* Real-time translation (via Google Translate)
* Text-to-speech playback (gTTS + pygame)
* Pause / Resume processing from the keyboard
* Multi-threaded architecture with queues
* Rolling audio buffer with silence detection

---

## Architecture Overview

The pipeline is split into independent worker threads connected by queues:

```
Microphone
   ↓
Rolling Audio Buffer
   ↓
Audio Slicer (overlapping windows)
   ↓
Whisper / OpenAI Transcription
   ↓
Transcript Cleaner (overlap removal)
   ↓
Translator
   ↓
Text-to-Speech
   ↓
Audio Playback
```

Each stage runs in its own thread and communicates via thread-safe queues.

---

## Main Components

### Audio Capture

* Uses `sounddevice` to capture microphone audio
* Maintains a rolling buffer (~60 seconds)
* Supports real-time processing

### Audio Slicing

* Extracts overlapping audio windows every few seconds
* Skips silent segments using amplitude thresholding

### Transcription

* Sends WAV audio slices to OpenAI’s transcription API
* Supports configurable language and temperature
* Saves audio slices for debugging

### Transcript Cleaning

* Uses `difflib.SequenceMatcher`
* Removes repeated phrases caused by overlapping audio windows
* Maintains a rolling text history for comparison

### Translation

* Asynchronously translates cleaned transcripts into configured target languages

### Text-to-Speech

* Converts translated text to speech using gTTS
* Plays audio using `pygame.mixer`

---

## ⏸ Pause / Resume Control

The pipeline can be paused and resumed at runtime using keyboard input:

* Press **`p`** → Pause / Resume processing

This is implemented using a shared `threading.Event` (`pause_event`) that all workers respect.

---

## Requirements

### Python Version

* Python **3.9+** recommended

### Python Dependencies

Install required packages with:

```bash
pip install numpy sounddevice soundfile whisper openai googletrans gtts librosa pygame
```

> ⚠️ `whisper` may require `ffmpeg` to be installed on your system.

---

## API Key Configuration

The OpenAI API client is initialized in the script:

```python
client = OpenAI(api_key="YOUR_API_KEY", timeout=60)
```

**Important:**
Do not commit your real API key to version control.
Use environment variables for production use.

---

## Running the Application

Simply run:

```bash
python main.py
```

Once running:

* Microphone recording starts automatically
* Transcription and translation happen continuously
* Translated speech is played back in real time
* Press **`p`** to pause or resume

---

## Language Configuration

Target languages can be configured here:

```python
lang_config = {
    "de": "German"
}
```

You can add more languages as needed.

---

## Known Limitations

* Uses polling and fixed sleep intervals (not event-driven)
* No GUI (terminal-based control)
* Translation library (`googletrans`) may be unstable at times
* Not optimized for low-latency broadcasting (e.g., Icecast) out of the box

---

## Future Improvements

* GUI control panel (Tkinter / Qt)
* Icecast or WebRTC streaming support
* Configurable audio devices
* Better async handling for translation and TTS
* Graceful shutdown and resource cleanup
* Logging instead of `print()` statements

---

## License

This project is the sole property of Quest Digital and it is not opensource
Ensure you comply with the terms of service of OpenAI, Google Translate, and any third-party libraries used.

---

