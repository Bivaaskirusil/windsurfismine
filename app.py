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
    """Fetch working proxies from Proxifly's free proxy list"""
    try:
        # Try to get US proxies first (most likely to work with YouTube)
        response = requests.get('https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/countries/US/data.txt', timeout=10)
        if response.status_code == 200:
            proxies = [f'http://{proxy.strip()}' for proxy in response.text.split('\n') if proxy.strip()]
            if proxies:
                return proxies
        
        # If US proxies fail, try global HTTP proxies
        response = requests.get('https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/http/data.txt', timeout=10)
        if response.status_code == 200:
            proxies = [f'http://{proxy.strip()}' for proxy in response.text.split('\n') if proxy.strip()]
            if proxies:
                return proxies
                
    except Exception as e:
        print(f"Error fetching proxies: {e}")
    
    # Fallback to some known good proxies if the API fails
    return [
        'http://51.79.50.31:9300',
        'http://45.77.56.114:3128',
        'http://185.199.229.156:7492',
        'http://185.199.228.220:7300',
        'http://185.199.229.156:7492'
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
        'extract_flat': True,  # Crucial for fetching info without full download
        'socket_timeout': 30,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'nocheckcertificate': True, # Skip SSL certificate verification
        'ignoreerrors': True,       # Continue on download errors
        'forceip': 4,             # Force IPv4, can help in some environments
        # 'verbose': True, # Uncomment for detailed yt-dlp logs if issues persist
    }

    if proxy:
        try:
            # Ensure proxy URL has a scheme
            if not urlparse(proxy).scheme:
                proxy_url = f'http://{proxy}' # Default to http if not specified
            else:
                proxy_url = proxy
            options['proxy'] = proxy_url
            print(f"Using proxy: {proxy_url}")
        except Exception as e:
            print(f"Error setting up proxy {proxy}: {e}. Proceeding without proxy.")
            if 'proxy' in options: del options['proxy']
    else:
        # Ensure no stale proxy setting if proxy is None
        if 'proxy' in options: del options['proxy']
        print("No proxy configured or proxy setup failed, attempting direct connection.")

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
