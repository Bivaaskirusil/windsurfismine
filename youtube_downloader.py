import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import yt_dlp
import os
import threading
from PIL import Image, ImageTk
from urllib.request import urlopen
import io

class YouTubeDownloader:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Video Downloader")
        self.root.geometry("800x600")
        
        # Create main frame
        self.main_frame = ttk.Frame(root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # URL input
        ttk.Label(self.main_frame, text="YouTube URL:").grid(row=0, column=0, sticky=tk.W)
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(self.main_frame, textvariable=self.url_var, width=50)
        self.url_entry.grid(row=0, column=1, padx=5, pady=5)
        
        # Fetch button
        self.fetch_button = ttk.Button(self.main_frame, text="Fetch Info", command=self.fetch_video_info)
        self.fetch_button.grid(row=0, column=2, padx=5, pady=5)
        
        # Video info frame
        self.info_frame = ttk.LabelFrame(self.main_frame, text="Video Info", padding="5")
        self.info_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        
        # Thumbnail
        self.thumbnail_label = ttk.Label(self.info_frame)
        self.thumbnail_label.grid(row=0, column=0, padx=5, pady=5)
        
        # Video details
        self.title_var = tk.StringVar()
        self.title_label = ttk.Label(self.info_frame, textvariable=self.title_var)
        self.title_label.grid(row=0, column=1, padx=5, pady=5)
        
        # Format selection
        ttk.Label(self.info_frame, text="Select Format:").grid(row=1, column=0, sticky=tk.W)
        self.format_var = tk.StringVar()
        self.format_combo = ttk.Combobox(self.info_frame, textvariable=self.format_var, state='readonly')
        self.format_combo.grid(row=1, column=1, padx=5, pady=5)
        
        # Download button
        self.download_button = ttk.Button(self.main_frame, text="Download", command=self.download_video)
        self.download_button.grid(row=2, column=0, columnspan=3, pady=10)
        
        # Progress bar
        self.progress = ttk.Progressbar(self.main_frame, length=300)
        self.progress.grid(row=3, column=0, columnspan=3, pady=10)
        
        # Status label
        self.status_var = tk.StringVar()
        self.status_label = ttk.Label(self.main_frame, textvariable=self.status_var)
        self.status_label.grid(row=4, column=0, columnspan=3, pady=5)
        
        # Output directory
        ttk.Label(self.main_frame, text="Output Directory:").grid(row=5, column=0, sticky=tk.W)
        self.output_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Downloads"))
        self.output_entry = ttk.Entry(self.main_frame, textvariable=self.output_var, width=50)
        self.output_entry.grid(row=5, column=1, padx=5, pady=5)
        ttk.Button(self.main_frame, text="Browse", command=self.browse_output).grid(row=5, column=2, padx=5, pady=5)
        
        self.video_info = None
        self.formats = []
        
    def browse_output(self):
        directory = filedialog.askdirectory()
        if directory:
            self.output_var.set(directory)
    
    def fetch_video_info(self):
        url = self.url_var.get()
        if not url:
            messagebox.showerror("Error", "Please enter a YouTube URL")
            return
            
        self.status_var.set("Fetching video info...")
        self.root.update()
        
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.video_info = ydl.extract_info(url, download=False)
                
                # Get formats
                self.formats = []
                for f in self.video_info['formats']:
                    if f.get('format_note'):
                        format_str = f"{f['format_note']} - {f['ext']} ({f['format_id']})"
                        self.formats.append((format_str, f['format_id']))
                
                # Update UI
                self.title_var.set(f"Title: {self.video_info['title']}")
                self.format_combo['values'] = [f[0] for f in self.formats]
                if self.formats:
                    self.format_combo.current(0)
                
                # Load thumbnail
                self.load_thumbnail()
                
                self.status_var.set("Ready to download")
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to fetch video info: {str(e)}")
            self.status_var.set("Error fetching info")
            
    def load_thumbnail(self):
        try:
            if 'thumbnail' in self.video_info:
                with urlopen(self.video_info['thumbnail']) as response:
                    img_data = response.read()
                    img = Image.open(io.BytesIO(img_data))
                    img = img.resize((200, 150))
                    photo = ImageTk.PhotoImage(img)
                    self.thumbnail_label.configure(image=photo)
                    self.thumbnail_label.image = photo
        except:
            pass
    
    def download_video(self):
        if not self.video_info:
            messagebox.showerror("Error", "Please fetch video info first")
            return
            
        selected_format = self.format_var.get()
        if not selected_format:
            messagebox.showerror("Error", "Please select a format")
            return
            
        format_id = next(f[1] for f in self.formats if f[0] == selected_format)
        
        output_dir = self.output_var.get()
        if not os.path.exists(output_dir):
            messagebox.showerror("Error", "Output directory does not exist")
            return
            
        self.status_var.set("Downloading...")
        self.progress['value'] = 0
        
        # Create download thread
        download_thread = threading.Thread(target=self._download_video, args=(format_id, output_dir))
        download_thread.start()
    
    def _download_video(self, format_id, output_dir):
        ydl_opts = {
            'format': format_id,
            'outtmpl': os.path.join(output_dir, '%(title)s.%(ext)s'),
            'progress_hooks': [self.progress_hook],
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url_var.get()])
                self.status_var.set("Download complete!")
                messagebox.showinfo("Success", "Download completed successfully!")
        except Exception as e:
            self.status_var.set("Error downloading")
            messagebox.showerror("Error", f"Download failed: {str(e)}")
            
    def progress_hook(self, d):
        if d['status'] == 'downloading':
            if 'total_bytes_estimate' in d and 'downloaded_bytes' in d:
                percent = (d['downloaded_bytes'] / d['total_bytes_estimate']) * 100
                self.progress['value'] = percent
                self.root.update()

if __name__ == "__main__":
    root = tk.Tk()
    app = YouTubeDownloader(root)
    root.mainloop()
