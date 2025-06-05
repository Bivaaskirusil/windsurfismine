from flask import Flask, render_template, request, jsonify
import yt_dlp
import os
import threading
import json
import random
import requests
import concurrent.futures
from urllib.parse import urlparse
from datetime import datetime, timedelta

class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.last_updated = None
        self.update_interval = timedelta(minutes=30)  # Update proxies every 30 minutes
        self.test_url = 'https://www.youtube.com/robots.txt'  # Lightweight URL for testing
        self.timeout = 5  # seconds
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
        })

    def is_proxy_working(self, proxy):
        """Test if a proxy is working"""
        proxies = {
            'http': proxy,
            'https': proxy
        }
        try:
            response = self.session.get(
                self.test_url,
                proxies=proxies,
                timeout=self.timeout,
                verify=False
            )
            return response.status_code == 200
        except:
            return False

    def fetch_proxies(self):
        """Fetch proxies from multiple sources"""
        proxy_sources = [
            self._fetch_geonode_proxies,
            self._fetch_proxyscrape_proxies,
            self._fetch_proxylist_proxies
        ]
        
        all_proxies = set()
        
        # Fetch proxies from all sources in parallel
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_source = {executor.submit(source): source for source in proxy_sources}
            for future in concurrent.futures.as_completed(future_to_source):
                try:
                    proxies = future.result()
                    all_proxies.update(proxies)
                except Exception as e:
                    print(f"Error fetching proxies: {e}")
        
        return list(all_proxies)

    def _fetch_geonode_proxies(self):
        """Fetch proxies from Geonode API"""
        try:
            url = 'https://proxylist.geonode.com/api/proxy-list?limit=50&page=1&sort_by=lastChecked&sort_type=desc&speed=fast&protocols=http%2Chttps'
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return [f"http://{p['ip']}:{p['port']}" for p in data.get('data', [])]
        except Exception as e:
            print(f"Error fetching from Geonode: {e}")
        return []

    def _fetch_proxyscrape_proxies(self):
        """Fetch proxies from ProxyScrape"""
        try:
            url = 'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=US,UK,CA&ssl=yes&anonymity=elite'
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return [f"http://{line.strip()}" for line in response.text.split('\n') if line.strip()]
        except Exception as e:
            print(f"Error fetching from ProxyScrape: {e}")
        return []

    def _fetch_proxylist_proxies(self):
        """Fetch proxies from ProxyList.download"""
        try:
            url = 'https://www.proxy-list.download/api/v1/get?type=http&anon=elite&country=US,UK,CA'
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return [f"http://{line.strip()}" for line in response.text.split('\n') if line.strip()]
        except Exception as e:
            print(f"Error fetching from ProxyList: {e}")
        return []

    def update_proxies(self):
        """Update the proxy list"""
        if self.last_updated and (datetime.now() - self.last_updated) < self.update_interval:
            return
            
        print("Updating proxy list...")
        new_proxies = self.fetch_proxies()
        
        # Test all new proxies in parallel
        working_proxies = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            future_to_proxy = {executor.submit(self.is_proxy_working, proxy): proxy for proxy in new_proxies}
            for future in concurrent.futures.as_completed(future_to_proxy):
                proxy = future_to_proxy[future]
                try:
                    if future.result():
                        working_proxies.append(proxy)
                except Exception as e:
                    print(f"Error testing proxy {proxy}: {e}")
        
        self.proxies = working_proxies
        self.last_updated = datetime.now()
        print(f"Updated proxy list. Found {len(self.proxies)} working proxies.")
        
        # If no working proxies were found, use some fallbacks
        if not self.proxies:
            self.proxies = [
                'http://51.79.50.31:9300',
                'http://45.77.56.114:3128',
                'http://185.199.229.156:7492'
            ]
            print("Using fallback proxies")

    def get_random_proxy(self):
        """Get a random working proxy"""
        self.update_proxies()
        return random.choice(self.proxies) if self.proxies else None

# Initialize proxy manager
proxy_manager = ProxyManager()

def get_random_proxy():
    """Get a random working proxy using ProxyManager"""
    return proxy_manager.get_random_proxy()

def get_ytdlp_options(proxy=None):
    """Get yt-dlp options with proxy settings and verbose logging"""
    options = {
        'quiet': False,  # Set to False to see yt-dlp output
        'no_warnings': False,  # Show warnings
        'extract_flat': True,  # Crucial for fetching info without full download
        'socket_timeout': 30,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'DNT': '1',
            'Connection': 'keep-alive',
        },
        'nocheckcertificate': True,  # Skip SSL certificate verification
        'ignoreerrors': False,  # Set to False to see all errors
        'forceip': 4,  # Force IPv4, can help in some environments
        'verbose': True,  # Enable verbose logging
        'extractor_retries': 3,  # Retry on extraction errors
        'fragment_retries': 10,  # Retry on fragment errors
        'retries': 10,  # General retries
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'player_skip': ['configs', 'webpage', 'js'],
                'skip': ['dash', 'hls']
            }
        },
        'compat_opts': ['no-youtube-unavailable-video']
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
