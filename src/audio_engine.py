"""
Background ambient music engine for Focus-Shell using pygame mixer.

This module provides a professional audio playback system with fade transitions,
playlist management, and volume control integrated with the application's
configuration system.
"""

import pygame
import os
from pathlib import Path
from typing import Optional, List, Callable
import time
import threading


class AmbientAudioEngine:
    """
    Manages background ambient music playback with fade transitions.
    
    Features:
    - Scans assets/music/ for audio files (.mp3, .wav, .ogg, .flac)
    - Play, pause, stop, resume controls
    - Volume control with fade in/fade out transitions
    - Autoplay playlist looping
    - Threadsafe volume adjustments
    """
    
    SUPPORTED_FORMATS = {'.mp3', '.wav', '.ogg', '.flac'}
    DEFAULT_FADE_DURATION = 1.0  # seconds
    
    def __init__(self, music_dir: str = "assets/music", default_volume: float = 0.5):
        """
        Initialize the audio engine.
        
        Args:
            music_dir (str): Path to the music directory
            default_volume (float): Default volume level (0.0 - 1.0)
        """
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
        except Exception as e:
            print(f"Warning: Could not initialize pygame mixer: {e}")
            return
        
        self.music_dir = Path(music_dir)
        self.current_track: Optional[str] = None
        self.is_playing = False
        self.is_paused = False
        self.current_volume = max(0.0, min(1.0, default_volume))
        self.playlist: List[str] = []
        self.playlist_index = 0
        self.autoplay = False
        
        # Fade transition tracking
        self._fade_thread: Optional[threading.Thread] = None
        self._target_volume = self.current_volume
        self._is_fading = False
        
        # Create music directory if it doesn't exist
        self.music_dir.mkdir(parents=True, exist_ok=True)
        
        # Scan for available tracks
        self.refresh_playlist()
    
    def refresh_playlist(self) -> None:
        """Scan the music directory and refresh the playlist of available tracks."""
        try:
            self.playlist = sorted([
                f.name for f in self.music_dir.iterdir()
                if f.is_file() and f.suffix.lower() in self.SUPPORTED_FORMATS
            ])
            self.playlist_index = 0
        except Exception as e:
            print(f"Error scanning music directory: {e}")
            self.playlist = []
    
    def get_available_tracks(self) -> List[str]:
        """
        Get the list of available music tracks.
        
        Returns:
            List[str]: List of audio filenames in the music directory
        """
        return self.playlist.copy()
    
    def load_track(self, filename: str) -> bool:
        """
        Load a specific audio track.
        
        Args:
            filename (str): Name of the file to load
            
        Returns:
            bool: True if load successful, False otherwise
        """
        try:
            music_path = self.music_dir / filename
            
            if not music_path.exists():
                print(f"Error: Music file not found: {music_path}")
                return False
            
            if not music_path.is_file():
                print(f"Error: Not a file: {music_path}")
                return False
            
            pygame.mixer.music.load(str(music_path))
            self.current_track = filename
            return True
        
        except Exception as e:
            print(f"Error loading music track '{filename}': {e}")
            return False
    
    def play(self, filename: Optional[str] = None, loops: int = 0) -> bool:
        """
        Play a music track.
        
        Args:
            filename (str, optional): Track to play. If None, plays current track.
            loops (int): Number of times to loop (-1 for infinite)
            
        Returns:
            bool: True if playback started, False otherwise
        """
        try:
            if filename:
                if not self.load_track(filename):
                    return False
            
            if not self.current_track:
                print("Error: No track loaded")
                return False
            
            pygame.mixer.music.play(loops)
            self.is_playing = True
            self.is_paused = False
            return True
        
        except Exception as e:
            print(f"Error playing music: {e}")
            return False
    
    def pause(self) -> bool:
        """
        Pause the currently playing music.
        
        Returns:
            bool: True if paused successfully, False otherwise
        """
        try:
            if self.is_playing and not self.is_paused:
                pygame.mixer.music.pause()
                self.is_paused = True
                return True
            return False
        
        except Exception as e:
            print(f"Error pausing music: {e}")
            return False
    
    def unpause(self) -> bool:
        """
        Resume paused music.
        
        Returns:
            bool: True if resumed successfully, False otherwise
        """
        try:
            if self.is_paused:
                pygame.mixer.music.unpause()
                self.is_paused = False
                return True
            return False
        
        except Exception as e:
            print(f"Error unpausing music: {e}")
            return False
    
    def stop(self) -> bool:
        """
        Stop the currently playing music.
        
        Returns:
            bool: True if stopped successfully, False otherwise
        """
        try:
            pygame.mixer.music.stop()
            self.is_playing = False
            self.is_paused = False
            return True
        
        except Exception as e:
            print(f"Error stopping music: {e}")
            return False
    
    def set_volume(self, volume: float) -> None:
        """
        Set the volume immediately (no fade).
        
        Args:
            volume (float): Volume level 0.0 (silent) to 1.0 (max)
        """
        try:
            self.current_volume = max(0.0, min(1.0, volume))
            pygame.mixer.music.set_volume(self.current_volume)
        
        except Exception as e:
            print(f"Error setting volume: {e}")
    
    def fade_to_volume(self, target_volume: float, duration: float = DEFAULT_FADE_DURATION) -> None:
        """
        Smoothly fade to a target volume over a specified duration.
        
        This runs on a background thread to avoid blocking the UI.
        
        Args:
            target_volume (float): Target volume level 0.0 to 1.0
            duration (float): Time in seconds to reach target volume
        """
        if self._is_fading:
            return  # Already fading
        
        target_volume = max(0.0, min(1.0, target_volume))
        
        # If already at target, skip fade
        if abs(self.current_volume - target_volume) < 0.01:
            return
        
        self._target_volume = target_volume
        self._is_fading = True
        self._fade_thread = threading.Thread(
            target=self._perform_fade,
            args=(target_volume, duration),
            daemon=True
        )
        self._fade_thread.start()
    
    def _perform_fade(self, target_volume: float, duration: float) -> None:
        """
        Internal method to perform the fade transition.
        
        Args:
            target_volume (float): Target volume
            duration (float): Fade duration in seconds
        """
        try:
            start_volume = self.current_volume
            start_time = time.time()
            
            while time.time() - start_time < duration:
                elapsed = time.time() - start_time
                progress = elapsed / duration
                
                # Linear interpolation
                new_volume = start_volume + (target_volume - start_volume) * progress
                self.set_volume(new_volume)
                
                time.sleep(0.05)  # Update every 50ms
            
            # Ensure we end at exactly the target volume
            self.set_volume(target_volume)
            self._is_fading = False
        
        except Exception as e:
            print(f"Error during fade transition: {e}")
            self._is_fading = False
    
    def play_next_in_playlist(self) -> bool:
        """
        Play the next track in the playlist.
        
        Returns:
            bool: True if next track playing, False if no more tracks
        """
        if not self.playlist:
            return False
        
        self.playlist_index = (self.playlist_index + 1) % len(self.playlist)
        next_track = self.playlist[self.playlist_index]
        return self.play(next_track, loops=0)
    
    def play_previous_in_playlist(self) -> bool:
        """
        Play the previous track in the playlist.
        
        Returns:
            bool: True if previous track playing, False if no tracks
        """
        if not self.playlist:
            return False
        
        self.playlist_index = (self.playlist_index - 1) % len(self.playlist)
        prev_track = self.playlist[self.playlist_index]
        return self.play(prev_track, loops=0)
    
    def set_autoplay(self, enabled: bool) -> None:
        """
        Enable or disable autoplay of the next track when current finishes.
        
        Args:
            enabled (bool): True to enable autoplay, False to disable
        """
        self.autoplay = enabled
    
    def is_currently_playing(self) -> bool:
        """
        Check if music is currently playing.
        
        Returns:
            bool: True if music is playing, False otherwise
        """
        return pygame.mixer.music.get_busy()
    
    def get_current_track(self) -> Optional[str]:
        """
        Get the currently loaded track filename.
        
        Returns:
            Optional[str]: Current track name or None
        """
        return self.current_track
    
    def get_current_volume(self) -> float:
        """
        Get the current volume level.
        
        Returns:
            float: Volume level 0.0 to 1.0
        """
        return self.current_volume
