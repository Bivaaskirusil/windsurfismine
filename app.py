from flask import Flask, render_template, request, jsonify
import yt_dlp
import os
import threading
import json
import random
import requests
from urllib.parse import urlparse

# List of free proxy servers (you might want to use a paid proxy service for production)
PROXY_SERVERS = [
    'http://51.79.50.31:9300',  # Example proxy (replace with actual working proxies)
    'http://51.79.50.31:9300',  # Example proxy (replace with actual working proxies)
    'http://51.79.50.31:9300'   # Example proxy (replace with actual working proxies)
]

def fetch_working_proxies():
    """Fetch working proxies from a free proxy provider"""
    try:
        response = requests.get('https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=US,UK&ssl=yes&anonymity=elite')
        if response.status_code == 200:
            proxies = [f'http://{proxy.strip()}' for proxy in response.text.split('\r\n') if proxy.strip()]
            return proxies
    except Exception as e:
        print(f"Error fetching proxies: {e}")
    
    # Fallback to some known good proxies if the API fails
    return [
        'http://51.79.50.31:9300',
        'http://45.77.56.114:3128',
        'http://45.77.56.114:3128'
    ]

def get_random_proxy():
    """Get a random proxy from the list"""
    proxies = fetch_working_proxies()
    return random.choice(proxies) if proxies else None

def get_ytdlp_options(proxy=None):
    """Get yt-dlp options with proxy settings"""
    options = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'socket_timeout': 30,
        'nocheckcertificate': True,
        'source_address': '0.0.0.0',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
        }
    }
    
    if proxy:
        options['proxy'] = proxy
        # Parse the proxy URL to get the host and port
        parsed = urlparse(proxy)
        proxy_host = parsed.hostname
        proxy_port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        options['source_address'] = f'{proxy_host}:{proxy_port}'
    
    return options

app = Flask(__name__)

# Configure output directory
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Downloads")
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/fetch_info', methods=['POST'])
def fetch_info():
    try:
        url = request.json.get('url')
        if not url:
            return jsonify({'error': 'URL is required'}), 400

        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            proxy = get_random_proxy()
            ydl_opts = get_ytdlp_options(proxy)
            
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    # If we get here, the request was successful
                    break
            except Exception as e:
                last_error = str(e)
                print(f"Attempt {attempt + 1} failed with proxy {proxy}: {last_error}")
                if attempt == max_retries - 1:
                    # Last attempt, try without proxy
                    print("All proxy attempts failed, trying direct connection")
                    ydl_opts = get_ytdlp_options(None)
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                        break
        
        formats = []
        for f in info['formats']:
            if f.get('format_note'):
                format_str = f"{f['format_note']} - {f['ext']} ({f['format_id']})"
                formats.append({
                    'label': format_str,
                    'id': f['format_id']
                })
        
        return jsonify({
            'title': info['title'],
            'thumbnail': info.get('thumbnail'),
            'formats': formats
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download', methods=['POST'])
def download():
    try:
        data = request.json
        url = data.get('url')
        format_id = data.get('format_id')
        
        if not url or not format_id:
            return jsonify({'error': 'URL and format_id are required'}), 400

        # Try with proxy first, fallback to direct connection
        proxy = get_random_proxy()
        ydl_opts = get_ytdlp_options(proxy)
        ydl_opts.update({
            'format': format_id,
            'outtmpl': os.path.join(OUTPUT_DIR, '%(title)s.%(ext)s'),
            'progress_hooks': [progress_hook],
        })

        def download_thread():
            max_retries = 3
            last_error = None
            
            for attempt in range(max_retries):
                proxy = get_random_proxy()
                current_opts = get_ytdlp_options(proxy)
                current_opts.update({
                    'format': format_id,
                    'outtmpl': os.path.join(OUTPUT_DIR, '%(title)s.%(ext)s'),
                    'progress_hooks': [progress_hook],
                })
                
                try:
                    with yt_dlp.YoutubeDL(current_opts) as ydl:
                        ydl.download([url])
                    # If we get here, download was successful
                    return
                except Exception as e:
                    last_error = str(e)
                    print(f"Download attempt {attempt + 1} failed with proxy {proxy}: {last_error}")
                    if attempt == max_retries - 1:
                        # Last attempt, try without proxy
                        print("All proxy attempts failed, trying direct connection")
                        current_opts = get_ytdlp_options(None)
                        current_opts.update({
                            'format': format_id,
                            'outtmpl': os.path.join(OUTPUT_DIR, '%(title)s.%(ext)s'),
                            'progress_hooks': [progress_hook],
                        })
                        with yt_dlp.YoutubeDL(current_opts) as ydl:
                            ydl.download([url])
                            return

        # Start download in a separate thread
        threading.Thread(target=download_thread).start()
        
        return jsonify({'message': 'Download started'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def progress_hook(d):
    if d['status'] == 'downloading':
        print(f"Progress: {d['downloaded_bytes']}/{d['total_bytes_estimate']}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
