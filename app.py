from flask import Flask, render_template, request, jsonify
import yt_dlp
import os
import threading
import json

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

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
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

        ydl_opts = {
            'format': format_id,
            'outtmpl': os.path.join(OUTPUT_DIR, '%(title)s.%(ext)s'),
            'progress_hooks': [progress_hook],
        }

        def download_thread():
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
            except Exception as e:
                print(f"Download failed: {str(e)}")

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
