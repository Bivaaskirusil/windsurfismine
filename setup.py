from setuptools import setup

setup(
    name="youtube-downloader",
    version="1.0.0",
    packages=["app"],
    install_requires=[
        "yt-dlp==2025.5.22",
        "requests==2.31.0",
        "Pillow==10.1.0",
        "Flask==3.0.0",
        "python-dotenv==1.0.0",
        "waitress==2.1.2",
        "gunicorn==21.2.0"
    ],
    entry_points={
        "console_scripts": [
            "youtube-downloader=app:main"
        ]
    }
)
