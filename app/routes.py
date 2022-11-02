
from app import app
from flask import send_file, request
import hashlib
from PIL import Image
from skimage.metrics import structural_similarity as ssim
import pprint
import numpy
import os
import random
import boto3
import time
import tempfile
import subprocess

@app.route('/', methods=['GET'])
@app.route('/index')
def index():
    return send_file('static/form.html')

@app.route('/letter.pdf', methods=['GET'])
def target_image():
    return send_file('static/letter.pdf')

@app.route('/collider', methods=['POST'])
def collider():
    files = request.files.getlist('files')
    if len(files) != 2:
        return "I need exactly two files, please."

    hashes_1 = get_hashes(files[0])
    hashes_2 = get_hashes(files[1])

    if hashes_1["md5"] != hashes_2["md5"] and hashes_1["sha1"] != hashes_2["sha1"]:
        return "Sorry, I need two files with the same hash (MD5 or SHA1)"

    # At this point, either sha1 or md5 matches on the files, are they jpegs?

    with open('app/static/letter.pdf', 'rb') as f:
        target_image = image_parse(f)
    assert target_image is not None

    try:
        im1 = image_parse(files[0])
    except Exception as e:
        return str(e)

    try:
        im2 = image_parse(files[1])
    except Exception as e:
        return str(e)

    # Are they the same size as our target image?
    if (
        im1.size[0] != im2.size[0]
        or im1.size[1] != im2.size[1]
        or target_image.size[0] != im1.size[0]
        or target_image.size[1] != im2.size[1]
    ):
        save_them(files[0], files[1])
        return "Sorry, the image sizes don't match"

    goodOne = None
    badOne = None

    # Do they look sufficiently the same? Or sufficiently different?

    target_gray = target_image

    alikes = []

    try:
        alike = compare_images(target_image, im1, target_gray, im1)
        print(f"alike1={alike}")
        if alike >= 0.99:
            goodOne = im1
        elif alike <= 0.92:
            badOne = im1
    except ImageComparisonException as e:
        save_them(files[0], files[1])
        return str(e)
    alikes.append(alike)

    try:
        alike = compare_images(target_image, im2, target_gray, im2)
        print(f"alike2={alike}")
        if alike >= 0.99 and goodOne is None:
            goodOne = im2
        elif alike <= 0.92 and badOne is None:
            badOne = im2
    except ImageComparisonException as e:
        save_them(files[0], files[1])
        return str(e)
    alikes.append(alike)


    if badOne is None:
        save_them(files[0], files[1])
        return f"Sorry, one image should be very different from mine {alikes[0]} {alikes[1]}"

    if goodOne is None:
        save_them(files[0], files[1])
        return f"Sorry, one image should be very similiar to mine {alikes[0]} {alikes[1]}"

    # Similiarity should be transitive, right? Just check it and make sure.
    try:
        if compare_images(im1, im2, im1, im2) >= 0.92:
            save_them(files[0], files[1])
            return "Sorry, your images are too similiar to each other"
    except ImageComparisonException as e:
        return str(e)

    # The user has met the challenge, give up the key...

    save_them(files[0], files[1], success=True)

    if hashes_1["sha1"] == hashes_2["sha1"]:
        with open("key.sha1", "r") as f:
            return f.read()

class FileProcessException(Exception):
    pass

class ImageComparisonException(Exception):
    pass

def compare_images(im1, im2, im1gray=None, im2gray=None):
    if im1.size != im2.size:
        print(im1.size, im2.size)
        raise ImageComparisonException("images are not the right size")

    if im2.getbands() != im2.getbands():
        raise ImageComparisonException("incorrect or missing color bands")

    # convert both images to grayscale if not already available
    if im1gray is None:
        im1gray = im1.convert("L")
    if im2gray is None:
        im2gray = im2.convert("L")

    pixels1 = numpy.array(im1gray.getdata()) / 255.0
    pixels2 = numpy.array(im2gray.getdata()) / 255.0
    return ssim(pixels1, pixels2)

def get_hashes(file):
    """Get the hashes for a fileobj (in one pass)"""
    hashfunnames = ("md5", "sha1", "sha256")
    hashfuns = [hashlib.new(f) for f in hashfunnames]
    while True:
        buf = file.read(8192)
        if len(buf) == 0:
            break
        for h in hashfuns:
            h.update(buf)

    file.seek(0)

    res = {}
    for i in range(len(hashfunnames)):
        res[hashfunnames[i]] = hashfuns[i].hexdigest()
    return res

def image_parse(file):
    with tempfile.TemporaryDirectory() as tmpdir:

        # render it into an image per page
        r = subprocess.call(['gs',
                               '-r300',
                               '-sDEVICE=pnggray',
                               '-dSAFER',
                               '-dNOPAUSE',
                               '-dBATCH',
                               '-o',
                               os.path.join(tmpdir, 'page-%04d.png'),
                               '-'],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            stdin=file)
        if r != 0:
            raise FileProcessException("file did not render")

        # we only want one page
        lst = os.listdir(tmpdir)
        if len(lst) < 1:
            raise FileProcessException("file did not render to page")
        if len(lst) > 1:
            raise FileProcessException("too many pages")

        return Image.open(os.path.join(tmpdir, lst[0]), mode='r')

def save_them(file1, file2, success=False):
    rnd = '%032x' % random.SystemRandom().randrange(16**32)
    stamp = '%d' % int(time.time())

    save_file(file1, success, 1, rnd, stamp)
    save_file(file2, success, 2, rnd, stamp)

def save_file(filedata, success, fileno, rnd, stamp):
    basename = 'fail'
    if success:
        basename = 'success'

    dstname = f"shattered/{basename}-{stamp}-{rnd}-{fileno}.pdf"
    s3 = boto3.client('s3')
    filedata.seek(0)
    s3.upload_fileobj(filedata, 'saintcon-hc-2022-jlw-store', dstname)
