from threading import Thread
import subprocess
import io
import logging
import json
import os
import socketserver
from http import server
from threading import Condition,Thread

class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()


class StreamingHandler(server.BaseHTTPRequestHandler):
    streaming_active = True  # สถานะเริ่มต้นคือเปิดการสตรีม
    output = StreamingOutput()
    def do_GET(self):
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/video_feed')
            self.end_headers()
        elif self.path == '/video_feed':
            self.serve_file('static/index.html')
        elif self.path.startswith('/static/'):
            self.serve_file(self.path.lstrip('/'))
        elif self.path == '/stream.mjpg':
            if StreamingHandler.streaming_active:
                self.send_response(200)
                self.send_header('Age', 0)
                self.send_header('Cache-Control', 'no-cache, private')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
                self.end_headers()
                try:
                    while StreamingHandler.streaming_active:
                        with StreamingHandler.output.condition:
                            StreamingHandler.output.condition.wait()
                            frame = StreamingHandler.output.frame
                        self.wfile.write(b'--FRAME\r\n')
                        self.send_header('Content-Type', 'image/jpeg')
                        self.send_header('Content-Length', len(frame))
                        self.end_headers()
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
                except Exception as e:
                    logging.warning(
                        'Removed streaming client %s: %s',
                        self.client_address, str(e))
            else:
                self.send_error(503, "Streaming is currently off")
        elif self.path == '/check_temperature_pi':
            temp = self.get_cpu_temperature()
            response = {
                "status": "success",
                "cpu_temp": temp
            }
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode('utf-8'))
        else:
            self.send_error(404)
            self.end_headers()
    def get_cpu_temperature(self):
        try:
            result = subprocess.run(['vcgencmd', 'measure_temp'], capture_output=True, text=True)
            temperature_str = result.stdout.strip()
            temperature = temperature_str.split('=')[1].replace("'C", "")
            return float(temperature)
        except Exception as e:
            print(f"Error retrieving temperature: {e}")
            return None

   
    def serve_file(self, path):
        try:
            # Open the file
            with open(path, 'rb') as file:
                content = file.read()
                # Determine the content type based on file extension
                if path.endswith('.html'):
                    content_type = 'text/html'
                elif path.endswith('.css'):
                    content_type = 'text/css'
                elif path.endswith('.js'):
                    content_type = 'application/javascript'
                elif path.endswith('.jpg') or path.endswith('.jpeg'):
                    content_type = 'image/jpeg'
                elif path.endswith('.png'):
                    content_type = 'image/png'
                else:
                    content_type = 'application/octet-stream'
                
                # Send the response
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', len(content))
                self.end_headers()
                self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, 'File not found')


class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True
