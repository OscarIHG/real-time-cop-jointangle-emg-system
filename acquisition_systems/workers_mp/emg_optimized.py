# -*- coding: utf-8 -*-
"""
Optimized EMG Worker with Multiprocessing

EMG was already relatively efficient, but this version provides:
1. Process isolation for stability
2. Better error handling and recovery
3. Optimized Bluetooth communication
4. Consistent performance under load
5. Improved data validation and filtering

Performance improvements:
- More stable under high CPU load
- Better Bluetooth connection management
- Reduced latency through process isolation
- Enhanced error recovery
"""

import time
import queue
import socket
from typing import Optional, Tuple
import re
from collections import deque

from .base import BaseWorkerMP
from acquisition_systems.common.types import EmgSample


class OptimizedEMGWorker(BaseWorkerMP):
    """
    OPTIMIZED EMG Worker with multiprocessing and enhanced Bluetooth handling.
    
    Improvements over original:
    - Separate process provides isolation from GUI load
    - Enhanced Bluetooth connection management
    - Better error recovery and reconnection logic
    - Optimized data parsing and validation
    - Circular buffer prevents memory buildup
    
    Expected performance: Stable acquisition at configured sample rate
    """
    
    def __init__(self, 
                 mac_address: str,
                 rfcomm_channel: int = 1,
                 vmin: float = 0.0, 
                 vmax: float = 5.0,
                 start_token: str = "1",
                 stop_token: str = "2",
                 allow_lf: bool = False,
                 buffer_size: int = 2000,
                 reconnect_attempts: int = 3,
                 timeout: float = 5.0):
        
        super().__init__("EMGOptimized", buffer_size, sample_rate=100.0)  # Typical EMG rate
        
        # Connection parameters
        self.mac_address = mac_address
        self.rfcomm_channel = rfcomm_channel
        self.timeout = timeout
        self.reconnect_attempts = reconnect_attempts
        
        # Data processing parameters
        self.vmin = float(vmin)
        self.vmax = float(vmax)
        self.start_token = start_token
        self.stop_token = stop_token
        self.allow_lf = allow_lf
        
        # Connection state
        self._socket = None
        self._connected = False
        
        # Data processing
        self.output_queue = queue.Queue(maxsize=20)
        self._data_buffer = deque(maxlen=1000)  # Circular buffer
        
        # Performance optimization: pre-compiled regex
        self._number_pattern = re.compile(r'^[-+]?\d*\.?\d+([eE][-+]?\d+)?$')
        
        # Line ending handling
        self._line_ending = b'\n' if allow_lf else b'\r\n'
        
        print(f"[EMGOptimized] Initialized for {mac_address}:{rfcomm_channel}")
        print(f"[EMGOptimized] Voltage range: {vmin:.2f} - {vmax:.2f}V")
        print(f"[EMGOptimized] Tokens: start='{start_token}', stop='{stop_token}'")
        print(f"[EMGOptimized] Line ending: {'LF' if allow_lf else 'CRLF'}")
    
    def setup_worker(self) -> bool:
        """Setup Bluetooth connection with retry logic."""
        print(f"[EMGOptimized] Setting up Bluetooth connection...")
        
        for attempt in range(self.reconnect_attempts):
            try:
                print(f"[EMGOptimized] Connection attempt {attempt + 1}/{self.reconnect_attempts}")
                
                # Create Bluetooth socket
                self._socket = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                self._socket.settimeout(self.timeout)
                
                # Connect to ESP32
                print(f"[EMGOptimized] Connecting to {self.mac_address}:{self.rfcomm_channel}...")
                self._socket.connect((self.mac_address, self.rfcomm_channel))
                
                print(f"[EMGOptimized] Connected successfully")
                
                # Send start token
                self._send_command(self.start_token)
                
                # Test communication with a brief read
                self._socket.settimeout(2.0)  # Short timeout for test
                test_data = self._socket.recv(64)
                if test_data:
                    print(f"[EMGOptimized] Communication test successful: {len(test_data)} bytes")
                
                self._socket.settimeout(self.timeout)  # Restore normal timeout
                self._connected = True
                
                print(f"[EMGOptimized] Setup complete")
                return True
                
            except Exception as e:
                print(f"[EMGOptimized] Connection attempt {attempt + 1} failed: {e}")
                
                if self._socket:
                    try:
                        self._socket.close()
                    except Exception:
                        pass
                    self._socket = None
                
                if attempt < self.reconnect_attempts - 1:
                    print(f"[EMGOptimized] Retrying in 2 seconds...")
                    time.sleep(2.0)
        
        print(f"[EMGOptimized] All connection attempts failed")
        return False
    
    def _send_command(self, command: str):
        """Send command to ESP32 with error handling."""
        try:
            cmd_bytes = (command + '\n').encode('utf-8')
            self._socket.send(cmd_bytes)
            print(f"[EMGOptimized] Sent command: '{command}'")
        except Exception as e:
            print(f"[EMGOptimized] Error sending command '{command}': {e}")
            raise
    
    def _read_line_optimized(self) -> Optional[str]:
        """Optimized line reading with better buffer management."""
        try:
            # Read data in chunks for efficiency
            chunk = self._socket.recv(256)
            if not chunk:
                return None
            
            # Add to buffer
            self._data_buffer.extend(chunk)
            
            # Look for complete line
            buffer_bytes = bytes(self._data_buffer)
            line_end_pos = buffer_bytes.find(self._line_ending)
            
            if line_end_pos >= 0:
                # Extract complete line
                line_bytes = buffer_bytes[:line_end_pos]
                
                # Remove processed data from buffer
                remaining = buffer_bytes[line_end_pos + len(self._line_ending):]
                self._data_buffer.clear()
                self._data_buffer.extend(remaining)
                
                # Decode line
                try:
                    return line_bytes.decode('utf-8').strip()
                except UnicodeDecodeError:
                    print(f"[EMGOptimized] Unicode decode error, skipping line")
                    return None
            
            # No complete line yet
            return None
            
        except socket.timeout:
            # Timeout is normal, don't log
            return None
        except Exception as e:
            print(f"[EMGOptimized] Error reading line: {e}")
            return None
    
    def _parse_emg_value(self, line: str) -> Optional[float]:
        """Optimized EMG value parsing with validation."""
        if not line:
            return None
        
        # Skip control tokens
        if line in (self.start_token, self.stop_token):
            return None
        
        # Quick regex validation (pre-compiled)
        if not self._number_pattern.match(line):
            return None
        
        try:
            value = float(line)
            
            # Clamp to valid range
            if value < self.vmin:
                value = self.vmin
            elif value > self.vmax:
                value = self.vmax
            
            return value
            
        except (ValueError, OverflowError):
            return None
    
    def _reconnect(self) -> bool:
        """Attempt to reconnect to ESP32."""
        print(f"[EMGOptimized] Attempting reconnection...")
        
        # Close existing connection
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        
        self._connected = False
        
        # Clear buffers
        self._data_buffer.clear()
        
        # Attempt reconnection
        return self.setup_worker()
    
    def process_data(self) -> bool:
        """Main processing loop with robust error handling."""
        if not self._connected or not self._socket:
            # Attempt reconnection
            if not self._reconnect():
                time.sleep(1.0)  # Wait before next attempt
                return True  # Continue trying
        
        try:
            # Read line from ESP32
            line = self._read_line_optimized()
            
            if line is not None:
                # Parse EMG value
                emg_value = self._parse_emg_value(line)
                
                if emg_value is not None:
                    # Create sample
                    sample = EmgSample(t=time.perf_counter(), value=emg_value)
                    
                    # Send to output queue (non-blocking)
                    try:
                        self.output_queue.put_nowait(sample)
                    except queue.Full:
                        # Remove old sample and add new one
                        try:
                            self.output_queue.get_nowait()
                            self.output_queue.put_nowait(sample)
                        except queue.Empty:
                            pass
            
            return True
            
        except ConnectionResetError:
            print(f"[EMGOptimized] Connection reset by peer")
            self._connected = False
            return True  # Try to reconnect
            
        except socket.error as e:
            print(f"[EMGOptimized] Socket error: {e}")
            self._connected = False
            return True  # Try to reconnect
            
        except Exception as e:
            print(f"[EMGOptimized] Unexpected error: {e}")
            # Don't reconnect on unexpected errors, just continue
            return True
    
    def cleanup_worker(self):
        """Clean up Bluetooth connection."""
        print(f"[EMGOptimized] Cleaning up connection...")
        
        # Send stop token
        if self._socket and self._connected:
            try:
                self._send_command(self.stop_token)
                time.sleep(0.1)  # Give ESP32 time to process
            except Exception as e:
                print(f"[EMGOptimized] Error sending stop token: {e}")
        
        # Close socket
        if self._socket:
            try:
                self._socket.close()
                print(f"[EMGOptimized] Socket closed")
            except Exception as e:
                print(f"[EMGOptimized] Error closing socket: {e}")
        
        self._socket = None
        self._connected = False
        
        print(f"[EMGOptimized] Cleanup complete")
    
    def get_latest_sample(self) -> Optional[EmgSample]:
        """Get the latest EMG sample (non-blocking)."""
        try:
            return self.output_queue.get_nowait()
        except queue.Empty:
            return None
    
    def has_data(self) -> bool:
        """Check if new data is available."""
        return not self.output_queue.empty()
    
    def is_connected(self) -> bool:
        """Check if ESP32 is connected."""
        return self._connected and self._socket is not None