import http.server
import socketserver
import webbrowser
import os
import threading

DIR = os.path.dirname(os.path.abspath(__file__))
PORT = 8000

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

# Try port 8000, fallback to 8001, 8002, ...
for attempt in range(PORT, PORT + 10):
    try:
        httpd = socketserver.TCPServer(('', attempt), Handler)
        PORT = attempt
        break
    except OSError:
        if attempt >= PORT + 9:
            print('ERROR: Could not find a free port (tried 8000-8009).')
            print('Close other applications and try again.')
            exit(1)
        continue

def open_browser():
    webbrowser.open(f'http://localhost:{PORT}/')

print(f'FSRS-6 v1.4 Simulator', flush=True)
print(f'URL: http://localhost:{PORT}/', flush=True)
print(f'Directory: {DIR}', flush=True)
print('Close this window to stop the server.', flush=True)
print(flush=True)

threading.Timer(1.5, open_browser).start()

try:
    httpd.serve_forever()
except KeyboardInterrupt:
    httpd.server_close()
