from flask import Flask, render_template, request, jsonify, send_file, abort
import yt_dlp
import os
import threading
import json
import random
import requests
import concurrent.futures
import psutil
import signal
import sys
from urllib.parse import urlparse
from datetime import datetime, timedelta
import tempfile
import shutil
import logging

# Helper for cookies file cleanup
import atexit
_temp_cookies_files = set()
def _cleanup_temp_cookies():
    for f in list(_temp_cookies_files):
        try:
            os.remove(f)
        except Exception:
            pass
atexit.register(_cleanup_temp_cookies)

# Initialize Flask app
app = Flask(__name__)

# Set up signal handler for graceful shutdown
def signal_handler(sig, frame):
    print('Shutting down gracefully...')
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.last_updated = None
        self.update_interval = timedelta(minutes=30)
        # Use a very lightweight test URL that's unlikely to change
        self.test_url = 'https://www.google.com/robots.txt'
        self.timeout = 3  # Reduce timeout for faster testing
        self.max_proxies = 5  # Maximum number of proxies to keep in the pool
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'text/plain',
            'Connection': 'close'
        })

    def is_proxy_working(self, proxy):
        """Test if a proxy is working with a quick request"""
        proxies = {'http': proxy, 'https': proxy}
        try:
            # First test with a quick connection
            response = self.session.head(
                'http://www.google.com/robots.txt',
                proxies=proxies,
                timeout=3,  # Shorter timeout for initial test
                verify=False,
                allow_redirects=True
            )
            
            if not (200 <= response.status_code < 300):
                return False
                
            # If first test passes, do a second test with YouTube
            response = self.session.head(
                'https://www.youtube.com/robots.txt',
                proxies=proxies,
                timeout=5,  # Slightly longer for YouTube
                verify=False,
                allow_redirects=True
            )
            
            return 200 <= response.status_code < 300
            
        except Exception as e:
            print(f"Proxy {proxy} failed: {str(e)[:100]}")
            return False

    def fetch_proxies(self):
        """Fetch proxies from multiple reliable sources"""
        proxy_sources = [
            self._fetch_static_proxies,  # Start with static proxies first
            self._fetch_geonode_proxies,
            self._fetch_proxyscrape_proxies
        ]
        
        all_proxies = set()
        
        # Fetch from sources with a short timeout
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_to_source = {executor.submit(source): source for source in proxy_sources}
            for future in concurrent.futures.as_completed(future_to_source, timeout=10):
                try:
                    proxies = future.result() or []
                    all_proxies.update(proxies)
                    if len(all_proxies) >= 20:  # Don't collect too many
                        break
                except Exception as e:
                    print(f"Warning: {future_to_source[future].__name__} failed: {str(e)[:100]}")
        
        return list(all_proxies)[:50]  # Return max 50 proxies

    def _fetch_static_proxies(self):
        """Return a list of reliable static proxies"""
        # Proxies from https://raw.githubusercontent.com/theriturajps/proxy-list/main/proxies.txt
        # Fetched on 2025-06-05
        return [
            'http://1.0.205.87:8080',
            'http://1.1.189.58:8080',
            'http://1.1.220.63:8080',
            'http://1.10.141.115:8080',
            'http://1.179.144.41:8080',
            'http://1.179.148.33:1080',
            'http://1.179.148.9:55636',
            'http://1.20.184.75:4153',
            'http://1.20.200.154:8081',
            'http://1.20.225.123:8080',
            'http://1.4.195.114:4145',
            'http://1.4.214.178:8080',
            'http://1.85.52.250:9797',
            'http://1.9.83.210:1337',
            'http://100.1.53.24:5678'
        ]
        
    def _fetch_geonode_proxies(self):
        """Fetch proxies from Geonode API"""
        try:
            url = 'https://proxylist.geonode.com/api/proxy-list?limit=20&page=1&sort_by=lastChecked&sort_type=desc&speed=fast&protocols=http%2Chttps'
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                return [f"http://{p['ip']}:{p['port']}" for p in data.get('data', [])[:10]]  # Return only first 10
        except Exception as e:
            print(f"Geonode API error: {str(e)[:100]}")
        return []

    def _fetch_proxyscrape_proxies(self):
        """Fetch proxies from ProxyScrape"""
        try:
            url = 'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=3000&country=US,UK,CA&ssl=yes&anonymity=elite'
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                proxies = [f"http://line.strip()" for line in response.text.split('\n') if line.strip()]
                return proxies[:10]  # Return only first 10
        except Exception as e:
            print(f"ProxyScrape error: {str(e)[:100]}")
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
        """Update the proxy list with better error handling and faster validation"""
        try:
            if self.last_updated and (datetime.now() - self.last_updated) < self.update_interval:
                return self.proxies
                
            print("Updating proxy list...")
            
            # Always include static proxies first
            all_proxies = self._fetch_static_proxies()
            
            # Add some dynamic proxies if available
            try:
                dynamic_proxies = self.fetch_proxies()
                all_proxies.extend(dynamic_proxies)
            except Exception as e:
                print(f"Warning: Could not fetch dynamic proxies: {e}")
            
            # Remove duplicates while preserving order
            seen = set()
            unique_proxies = []
            for proxy in all_proxies:
                if proxy not in seen:
                    seen.add(proxy)
                    unique_proxies.append(proxy)
            
            # Test proxies with timeout
            working_proxies = []
            test_futures = {}
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                # Submit all proxy tests
                for proxy in unique_proxies[:50]:  # Limit to first 50 to avoid too many tests
                    future = executor.submit(self.is_proxy_working, proxy)
                    test_futures[future] = proxy
                
                # Process results as they complete
                for future in concurrent.futures.as_completed(test_futures, timeout=30):
                    proxy = test_futures[future]
                    try:
                        if future.result():
                            working_proxies.append(proxy)
                            print(f"Found working proxy: {proxy}")
                            if len(working_proxies) >= 10:  # We only need a few good ones
                                break
                    except Exception as e:
                        print(f"Error testing proxy {proxy}: {e}")
            
            if working_proxies:
                self.proxies = working_proxies
                self.last_updated = datetime.now()
                print(f"Updated proxy list with {len(self.proxies)} working proxies.")
            else:
                print("No working proxies found, using fallback list")
                self._use_fallback_proxies()
                
        except Exception as e:
            print(f"Error in update_proxies: {e}")
            self._use_fallback_proxies()
            
        return self.proxies
    
    def _use_fallback_proxies(self):
        """Use fallback proxies when no others are available"""
        self.proxies = [
            'http://51.79.50.31:9300',
            'http://45.77.56.114:3128',
            'http://185.199.229.156:7492'
        ]
        self.last_updated = datetime.now()
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

def get_ytdlp_options(proxy=None, cookies_path=None):
    """Return yt-dlp options with NO proxy (direct connection only), and optional cookies file."""
    opts = {
        'quiet': True,
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'retries': 2,
        'socket_timeout': 10,
        'geo_bypass': True,
        'no_color': True,
        'concurrent_fragment_downloads': 2,
        'fragment_retries': 2,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
    }
    if cookies_path:
        opts['cookies'] = cookies_path
    return opts


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
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
            url = data.get('url')
            cookies_text = data.get('cookies_text')
        else:
            url = request.form.get('url')
            cookies_text = request.form.get('cookies_text')
            
        if not url:
            return jsonify({'error': 'URL is required'}), 400

        # Handle cookies: file upload or textarea
        cookies_path = None
        try:
            if 'cookies_file' in request.files and request.files['cookies_file']:
                cookies_file = request.files['cookies_file']
                fd, cookies_path = tempfile.mkstemp(prefix='yt_cookies_', suffix='.txt')
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(cookies_file.read().decode('utf-8'))
                _temp_cookies_files.add(cookies_path)
            elif cookies_text and cookies_text.strip():
                fd, cookies_path = tempfile.mkstemp(prefix='yt_cookies_', suffix='.txt')
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(cookies_text.strip())
                _temp_cookies_files.add(cookies_path)
        except Exception as e:
            return jsonify({'error': f'Failed to process cookies: {str(e)}'}), 400

        # Always use direct connection, no proxies, pass cookies if present
        ydl_opts = get_ytdlp_options(None, cookies_path)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            if cookies_path:
                try:
                    os.remove(cookies_path)
                    _temp_cookies_files.discard(cookies_path)
                except Exception:
                    pass
        
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
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
            url = data.get('url')
            format_id = data.get('format_id')
            cookies_text = data.get('cookies_text')
        else:
            url = request.form.get('url')
            format_id = request.form.get('format_id')
            cookies_text = request.form.get('cookies_text')
            
        if not url or not format_id:
            return jsonify({'error': 'URL and format_id are required'}), 400
            
        # Handle cookies: file upload or textarea
        cookies_path = None
        try:
            if 'cookies_file' in request.files and request.files['cookies_file']:
                cookies_file = request.files['cookies_file']
                fd, cookies_path = tempfile.mkstemp(prefix='yt_cookies_', suffix='.txt')
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(cookies_file.read().decode('utf-8'))
                _temp_cookies_files.add(cookies_path)
            elif cookies_text and cookies_text.strip():
                fd, cookies_path = tempfile.mkstemp(prefix='yt_cookies_', suffix='.txt')
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(cookies_text.strip())
                _temp_cookies_files.add(cookies_path)
        except Exception as e:
            return jsonify({'error': f'Failed to process cookies: {str(e)}'}), 400

        # Always use direct connection with cookies if provided
        ydl_opts = get_ytdlp_options(None, cookies_path)
        ydl_opts.update({
            'format': format_id,
            'outtmpl': os.path.join(OUTPUT_DIR, '%(title)s.%(ext)s'),
            'progress_hooks': [progress_hook],
        })

        def download_thread():
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                # If we get here, download was successful
                return {'status': 'success'}
            except Exception as e:
                error_msg = str(e)
                print(f"Download failed: {error_msg}")
                return {'status': 'error', 'message': error_msg}
            finally:
                # Clean up cookies file if it exists
                if cookies_path and os.path.exists(cookies_path):
                    try:
                        os.remove(cookies_path)
                        _temp_cookies_files.discard(cookies_path)
                    except Exception as e:
                        print(f"Failed to remove cookies file: {e}")
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
    port = int(os.environ.get('PORT', 10000))
    print(f"Starting server on port {port}")
    try:
        app.run(host='0.0.0.0', port=port, threaded=True)
    except Exception as e:
        print(f"Error starting server: {e}")
        raise
