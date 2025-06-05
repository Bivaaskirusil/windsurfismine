from flask import Flask, render_template, request, jsonify, send_file, abort
import yt_dlp
import os
import threading
import json
import http.cookiejar
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
        self.test_url = 'https://www.google.com/robots.txt'
        self.timeout = 3
        self.max_proxies = 5
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'text/plain',
            'Connection': 'close'
        })

    def is_proxy_working(self, proxy):
        try:
            response = self.session.get(self.test_url, proxies={"http": proxy, "https": proxy}, timeout=self.timeout)
            return response.status_code == 200
        except:
            return False

    def fetch_proxies(self):
        try:
            proxies = self._fetch_static_proxies()
            working_proxies = [p for p in proxies if self.is_proxy_working(p)]
            self.proxies = working_proxies[:self.max_proxies]
            self.last_updated = datetime.now()
            print(f"Updated proxy list with {len(self.proxies)} working proxies")
        except Exception as e:
            print(f"Error updating proxies: {e}")

    def _fetch_static_proxies(self):
        return [
            "http://45.95.203.1:80",
            "http://45.95.203.2:80",
            "http://45.95.203.3:80"
        ]

    def get_random_proxy(self):
        if not self.proxies or (datetime.now() - self.last_updated) > self.update_interval:
            self.fetch_proxies()
        return random.choice(self.proxies) if self.proxies else None

# Initialize proxy manager
proxy_manager = ProxyManager()

def get_random_proxy():
    """Get a random working proxy using ProxyManager"""
    return proxy_manager.get_random_proxy()

def get_ytdlp_options(proxy=None, cookies_path=None):
    """Return yt-dlp options with NO proxy (direct connection only), and optional cookies file."""
    opts = {
        'quiet': False,  # Set to True in production
        'verbose': True,  # For debugging
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'retries': 5,  # Increased retries
        'socket_timeout': 60,  # Increased timeout
        'extract_flat': False,
        'force_generic_extractor': False,
        'geo_bypass': True,
        'no_color': True,
        'concurrent_fragment_downloads': 2,
        'fragment_retries': 5,  # Increased retries
        'extractor_retries': 3,
        'nocheckcertificate': True,
        'ignore_no_formats_error': False,
        'extractor_args': {'youtube': {'skip': ['dash', 'hls']}},
        'compat_opts': ['youtube-skip-dash-manifest', 'youtube-skip-hls-manifest'],
        'format_sort': ['res:1080', 'ext:mp4'],  # Prefer 1080p MP4
        'merge_output_format': 'mp4',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Sec-Ch-Ua': '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Origin': 'https://www.youtube.com',
            'Referer': 'https://www.youtube.com/',
            'X-YouTube-Client-Name': '1',
            'X-YouTube-Client-Version': '2.20230628.08.00',
        },
        'cookiefile': None,  # Will be set if cookies_path is provided
        'cookiesfrombrowser': None,
        'extract_flat': False,
        'force_generic_extractor': False,
        'noplaylist': True,
        'ignore_no_formats_error': False,
    }
    
    if cookies_path and os.path.exists(cookies_path):
        try:
            print(f"Processing cookies from: {cookies_path}")
            
            # Set the cookies file path in yt-dlp options
            # yt-dlp will handle loading the cookies file itself
            opts['cookiefile'] = cookies_path
            
            # Verify the cookies file is in the correct format
            with open(cookies_path, 'r', encoding='utf-8') as f:
                first_line = f.readline().strip()
                if not (first_line == '# HTTP Cookie File' or first_line == '# Netscape HTTP Cookie File'):
                    print(f"Warning: Cookies file may not be in Netscape format. First line: {first_line}")
            
            # Load cookies to verify and log them
            try:
                cookie_jar = http.cookiejar.MozillaCookieJar()
                cookie_jar.load(cookies_path, ignore_discard=True, ignore_expires=True)
                
                if not cookie_jar:
                    print("Warning: No cookies found in the cookie jar")
                else:
                    print(f"Successfully loaded {len(cookie_jar)} cookies")
                    for i, cookie in enumerate(cookie_jar, 1):
                        print(f"  Cookie {i}: {cookie.name} (Domain: {cookie.domain}, Path: {cookie.path})")
                        
                    # Add important cookies to headers as well (for some sites)
                    important_cookies = [c for c in cookie_jar 
                                       if c.domain in ('.youtube.com', 'youtube.com', '.youtube-nocookie.com')
                                       and c.name in ('PREF', 'YSC', 'VISITOR_INFO1_LIVE', 'LOGIN_INFO', 'SID', 'HSID', 'SSID', 'APISID', 'SAPISID')]
                    
                    if important_cookies:
                        cookie_header = '; '.join([f'{c.name}={c.value}' for c in important_cookies])
                        opts['http_headers']['Cookie'] = cookie_header
                        print(f"Set Cookie header with {len(important_cookies)} important cookies")
            
            except Exception as e:
                print(f"Warning: Could not verify cookies: {str(e)}")
                import traceback
                traceback.print_exc()
                
        except Exception as e:
            print(f"Error processing cookies: {str(e)}")
            import traceback
            traceback.print_exc()
    else:
        print("No valid cookies file provided")
        
    return opts

def is_valid_cookie_line(line):
    """Check if a line from cookies text is a valid cookie line in Netscape format.
    
    Valid format:
    domain\tflag\tpath\tsecure\texpiration\tname\tvalue
    
    Where:
    - domain: The domain that created and can read the cookie
    - flag: A TRUE/FALSE value indicating if all machines within a given domain can access the cookie
    - path: The path within the domain that the cookie is valid for
    - secure: A TRUE/FALSE value indicating if a secure connection with the domain is needed to access the cookie
    - expiration: The UNIX time that the cookie will expire
    - name: The name of the cookie
    - value: The value of the cookie
    """
    line = line.strip()
    # Skip empty lines and comments
    if not line or line.startswith('#'):
        return False
        
    parts = line.split('\t')
    
    # Should have exactly 7 parts
    if len(parts) != 7:
        return False
        
    # Check domain is not empty and looks like a domain
    domain = parts[0].strip()
    if not domain or (not domain.startswith('.') and not domain.startswith('http')):
        return False
        
    # Check flag is TRUE/FALSE
    flag = parts[1].strip().upper()
    if flag not in ('TRUE', 'FALSE'):
        return False
        
    # Check path starts with /
    path = parts[2].strip()
    if not path.startswith('/'):
        return False
        
    # Check secure is TRUE/FALSE
    secure = parts[3].strip().upper()
    if secure not in ('TRUE', 'FALSE'):
        return False
        
    # Check expiration is a number
    try:
        int(parts[4].strip())
    except ValueError:
        return False
        
    # Check name and value are not empty
    if not parts[5].strip() or not parts[6].strip():
        return False
        
    return True

def clean_cookies_text(cookies_text):
    """Clean and validate cookies text in Netscape format.
    
    Ensures the cookie text has the proper header and valid cookie entries.
    """
    if not cookies_text or not cookies_text.strip():
        return None
        
    lines = cookies_text.strip().split('\n')
    valid_cookies = []
    has_header = False
    
    # Check for Netscape format header
    for i, line in enumerate(lines):
        line = line.strip()
        if line.startswith('# Netscape HTTP Cookie File') or line.startswith('# HTTP Cookie File'):
            has_header = True
            # Keep the header comments
            valid_cookies.append(line)
            # Add other header lines if they exist
            for j in range(i + 1, min(i + 3, len(lines))):
                if lines[j].strip().startswith('#'):
                    valid_cookies.append(lines[j].strip())
                else:
                    break
            break
    
    # If no header was found, add the standard Netscape header
    if not has_header:
        valid_cookies.extend([
            '# Netscape HTTP Cookie File',
            '# http://curl.haxx.se/rfc/cookie_spec.html',
            '# This is a generated file! Do not edit.',
            ''
        ])
    elif len(valid_cookies) < 3:  # Ensure we have the full header
        valid_cookies.extend([
            '# http://curl.haxx.se/rfc/cookie_spec.html',
            '# This is a generated file! Do not edit.',
            ''
        ])
    
    # Process cookie lines
    cookie_lines_added = False
    for line in lines:
        line = line.strip()
        if is_valid_cookie_line(line):
            # Ensure the line is properly tab-separated
            parts = [p.strip() for p in line.split('\t')]
            if len(parts) == 7:  # Ensure we have all parts
                valid_cookies.append('\t'.join(parts))
                cookie_lines_added = True
    
    if not cookie_lines_added:
        raise ValueError('No valid cookie entries found in the provided text')
    
    # Ensure the result ends with a newline
    result = '\n'.join(valid_cookies)
    if not result.endswith('\n'):
        result += '\n'
        
    return result

def save_cookies_to_file(cookies_text):
    """Save cookies text to a temporary file with proper Netscape format.
    
    The cookies file must be in Mozilla/Netscape format with the first line being either:
    # HTTP Cookie File or # Netscape HTTP Cookie File
    """
    if not cookies_text or not cookies_text.strip():
        return None
        
    try:
        # Clean and validate cookies
        cleaned_cookies = clean_cookies_text(cookies_text)
        if not cleaned_cookies:
            raise ValueError('No valid cookies found after cleaning')
            
        # Create a proper Netscape format cookies file
        fd, cookies_path = tempfile.mkstemp(prefix='yt_cookies_', suffix='.txt')
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            # Write Netscape format header - this is required by yt-dlp
            f.write('# Netscape HTTP Cookie File\n')
            f.write('# http://curl.haxx.se/rfc/cookie_spec.html\n')
            f.write('# This is a generated file! Do not edit.\n\n')
            
            # Write the cleaned cookies
            f.write(cleaned_cookies)
            
            # Ensure the file ends with a newline
            if not cleaned_cookies.endswith('\n'):
                f.write('\n')
        
        # Verify the cookies file can be loaded
        try:
            cookie_jar = http.cookiejar.MozillaCookieJar()
            cookie_jar.load(cookies_path, ignore_discard=True, ignore_expires=True)
            
            if not cookie_jar:
                raise ValueError('No valid cookies could be loaded from the provided text')
                
            print(f"Successfully loaded {len(cookie_jar)} cookies")
            for i, cookie in enumerate(cookie_jar, 1):
                print(f"  Cookie {i}: {cookie.name} (Domain: {cookie.domain}, Path: {cookie.path})")
                
            _temp_cookies_files.add(cookies_path)
            print(f"Cookies saved to: {cookies_path}")
            return cookies_path
            
        except Exception as e:
            # Clean up the invalid cookies file
            try:
                if os.path.exists(cookies_path):
                    os.remove(cookies_path)
            except Exception as cleanup_error:
                print(f"Error cleaning up cookies file: {cleanup_error}")
            
            print(f"Error loading cookies: {str(e)}")
            print("Cookies content (first 500 chars):")
            try:
                with open(cookies_path, 'r', encoding='utf-8') as f:
                    print(f.read(500) + ('...' if len(f.read(501)) > 500 else ''))
            except Exception as read_error:
                print(f"Could not read cookies file: {read_error}")
                
            raise Exception(f'Invalid cookies format: {str(e)}')
            
    except Exception as e:
        print(f"Error in save_cookies_to_file: {str(e)}")
        import traceback
        traceback.print_exc()
        raise Exception(f'Failed to process cookies: {str(e)}')

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
                cookies_text = request.files['cookies_file'].read().decode('utf-8')
            
            if cookies_text and cookies_text.strip():
                print("Processing cookies...")
                cookies_path = save_cookies_to_file(cookies_text)
                print(f"Using cookies from: {cookies_path}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'Failed to process cookies: {str(e)}'}), 400

        # Always use direct connection, no proxies, pass cookies if present
        ydl_opts = get_ytdlp_options(None, cookies_path)
        
        # Add retry logic for failed requests
        max_retries = 3
        retry_delay = 2  # seconds
        
        for attempt in range(max_retries):
            try:
                # Create a logger for yt-dlp to capture debug output
                class YTDLLogger:
                    def debug(self, msg):
                        if 'HTTP Error' in str(msg) or 'error' in str(msg).lower():
                            print(f"[yt-dlp DEBUG] {msg}")
                    def warning(self, msg):
                        print(f"[yt-dlp WARNING] {msg}")
                    def error(self, msg):
                        print(f"[yt-dlp ERROR] {msg}")
                
                ydl_opts['logger'] = YTDLLogger()
                
                # Clean up the URL to ensure it's in the correct format
                if 'youtube.com' in url or 'youtu.be' in url:
                    # Ensure we have a clean URL without extra parameters that might cause issues
                    from urllib.parse import urlparse, parse_qs, urlunparse
                    
                    parsed = urlparse(url)
                    if 'youtube.com' in parsed.netloc and parsed.path == '/watch':
                        # Keep only the 'v' parameter for YouTube watch URLs
                        params = parse_qs(parsed.query)
                        if 'v' in params:
                            clean_params = {'v': params['v'][0]}
                            parsed = parsed._replace(query='&'.join(f"{k}={v[0]}" for k, v in clean_params.items()))
                            url = urlunparse(parsed)
                
                print(f"Attempt {attempt + 1}/{max_retries} - Extracting info for URL: {url}")
                print(f"Using yt-dlp options: {ydl_opts}")
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    try:
                        info = ydl.extract_info(url, download=False)
                        print(f"Successfully extracted info. Available keys: {list(info.keys()) if info else 'None'}")
                        break  # Success, exit retry loop
                        
                    except yt_dlp.utils.DownloadError as e:
                        if 'HTTP Error 403' in str(e) and attempt < max_retries - 1:
                            print(f"Got 403 error, retrying in {retry_delay} seconds... (Attempt {attempt + 1}/{max_retries})")
                            import time
                            time.sleep(retry_delay)
                            continue
                        raise
                    
            except Exception as e:
                if attempt == max_retries - 1:  # Last attempt
                    print(f"Final attempt failed with error: {str(e)}")
                    print(f"Error type: {type(e).__name__}")
                    import traceback
                    traceback.print_exc()
                    raise Exception(f'Failed to extract video info after {max_retries} attempts: {str(e)}')
                continue
        
        if not info:
            raise Exception('No video information returned from YouTube')
            
        # Log some basic info about the video
        print(f"Video title: {info.get('title', 'N/A')}")
        print(f"Duration: {info.get('duration', 'N/A')} seconds")
        print(f"View count: {info.get('view_count', 'N/A')}")
        print(f"Uploader: {info.get('uploader', 'N/A')}")
        print(f"Available formats: {len(info.get('formats', []))}")
                    
                print(f"Video info: {info.keys()}")  # Debug log
                
                # Extract available formats
                formats = []
                if 'formats' not in info or not info['formats']:
                    raise Exception('No video formats available')
                    
                for f in info['formats']:
                    if not isinstance(f, dict):
                        print(f"Skipping invalid format: {f}")
                        continue
                        
                    format_note = f.get('format_note', f.get('ext', 'unknown'))
                    ext = f.get('ext', 'unknown')
                    format_id = f.get('format_id', '0')
                    
                    if not format_note:
                        format_note = f"{f.get('height', '?')}p" if f.get('height') else ext
                        
                    format_str = f"{format_note} - {ext} ({format_id})"
                    formats.append({
                        'label': format_str,
                        'id': format_id
                    })
                
                if not formats:
                    raise Exception('No valid formats found')
                
                response_data = {
                    'title': info.get('title', 'Untitled'),
                    'thumbnail': info.get('thumbnail'),
                    'formats': formats
                }
                
                return jsonify(response_data)
                
        except Exception as e:
            print(f"Error in fetch_info: {str(e)}")
            print(f"Error type: {type(e).__name__}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'Failed to fetch video info: {str(e)}'}), 500
            
        finally:
            # Clean up cookies file if it exists
            if cookies_path and os.path.exists(cookies_path):
                try:
                    os.remove(cookies_path)
                    _temp_cookies_files.discard(cookies_path)
                except Exception as e:
                    print(f"Error cleaning up cookies file: {e}")
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
                cookies_text = request.files['cookies_file'].read().decode('utf-8')
            
            if cookies_text and cookies_text.strip():
                print("Processing cookies for download...")
                cookies_path = save_cookies_to_file(cookies_text)
                print(f"Using cookies from: {cookies_path}")
        except Exception as e:
            import traceback
            traceback.print_exc()
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
                print(f"Starting download with options: {ydl_opts}")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                # If we get here, download was successful
                print("Download completed successfully")
            except Exception as e:
                print(f"Error in download thread: {str(e)}")
                import traceback
                traceback.print_exc()
            finally:
                # Clean up cookies file if it exists
                if cookies_path and os.path.exists(cookies_path):
                    try:
                        os.remove(cookies_path)
                        _temp_cookies_files.discard(cookies_path)
                    except Exception as e:
                        print(f"Error cleaning up cookies file: {e}")

        # Start download in a separate thread
        thread = threading.Thread(target=download_thread)
        thread.daemon = True
        thread.start()

        return jsonify({'status': 'Download started'})

    except Exception as e:
        # Clean up cookies file if it exists
        if cookies_path and os.path.exists(cookies_path):
            try:
                os.remove(cookies_path)
                _temp_cookies_files.discard(cookies_path)
            except Exception as e:
                print(f"Error cleaning up cookies file: {e}")
        
        print(f"Error in download: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

def progress_hook(d):
    if d['status'] == 'downloading':
        print(f"Downloading: {d.get('_percent_str', 'N/A')} of {d.get('_total_bytes_str', 'N/A')} at {d.get('_speed_str', 'N/A')}")
    elif d['status'] == 'finished':
        print("Download finished. Processing...")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f"Starting server on port {port}")
    try:
        # Use Gunicorn in production, but fall back to Flask's dev server for local testing
        from gunicorn.app.wsgiapp import WSGIApplication
        WSGIApplication("%s:app" % __name__).run()
    except ImportError:
        app.run(host='0.0.0.0', port=port, debug=True)
