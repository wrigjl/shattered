import hashlib
from PIL import Image

from flask import Flask
import os

app = Flask(__name__)

app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_PATH'] = 5 * 1024 * 1024

from app import routes

assert os.path.exists('app/static/isu.jpg')
assert os.path.exists('app/static/form.html')
assert os.path.exists('key.md5')
assert os.path.exists('key.sha1')
