#!/usr/bin/env python3
"""
Clawzd Low-Latency Desktop Audio Monitor Bridge.

Streams real-time or offline compiled audio timeline tracks from the Clawzd
backend direct to local ALSA/PulseAudio/PipeWire hardware DAC outputs.
"""
import os
import sys
import time
import json
import logging
import subprocess
import threading

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("clawzd.audio_monitor")

class DesktopAudioMonitor:
    def __init__(self, backend_url="http://localhost:8000"):
        self.backend_url = backend_url
        self.playing = False
        self.current_process = None
        
    def play_file(self, filepath: str):
        """Play a local audio file direct to PulseAudio/ALSA hardware DACs with ultra-low latency."""
        if not os.path.exists(filepath):
            logger.error("Audio file does not exist: %s", filepath)
            return False
            
        self.stop()
        self.playing = True
        
        # Use paplay (PulseAudio/PipeWire) or aplay (ALSA) based on availability
        play_cmd = None
        if shutil.which("paplay"):
            play_cmd = ["paplay", "--client-name=ClawzdMonitor", filepath]
        elif shutil.which("aplay"):
            play_cmd = ["aplay", "-q", filepath]
        else:
            play_cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", filepath]
            
        logger.info("Starting low-latency playback direct to hardware: %s", " ".join(play_cmd))
        
        def run_playback():
            try:
                self.current_process = subprocess.Popen(play_cmd)
                self.current_process.wait()
            except Exception as e:
                logger.error("Playback execution failed: %s", e)
            finally:
                self.playing = False
                self.current_process = None
                logger.info("Playback finished.")
                
        thread = threading.Thread(target=run_playback, daemon=True)
        thread.start()
        return True

    def stop(self):
        """Terminate any currently active hardware playback."""
        if self.current_process and self.current_process.poll() is None:
            logger.info("Stopping current playback...")
            self.current_process.terminate()
            try:
                self.current_process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self.current_process.kill()
        self.playing = False
        self.current_process = None

import shutil
if __name__ == "__main__":
    # If run directly, act as a standalone test player
    if len(sys.argv) < 2:
        print("Clawzd Audio Monitor Bridge")
        print("Usage: python3 desktop_audio_monitor.py <wav_file_path>")
        sys.exit(1)
        
    monitor = DesktopAudioMonitor()
    target_file = sys.argv[1]
    monitor.play_file(target_file)
    
    # Wait for playback to complete
    try:
        while monitor.playing:
            time.sleep(0.1)
    except KeyboardInterrupt:
        monitor.stop()
        print("\nPlayback interrupted.")
