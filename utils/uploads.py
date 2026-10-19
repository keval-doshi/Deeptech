"""Image upload handling.

Uploads are validated by extension, size and actual decoded content, then
re-encoded with Pillow. Re-encoding strips metadata (EXIF/GPS) and defeats
polyglot files. Filenames are random, so user input never reaches the path.
"""
import os
import uuid

from flask import current_app
from PIL import Image, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 40_000_000  # decompression-bomb guard

MAX_DIMENSIONS = {"logo": (512, 512), "cover": (1920, 1080), "photo": (600, 600), "image": (1600, 1200)}


class UploadError(ValueError):
    pass


def save_image(file_storage, subdir, kind="image"):
    """Validate and store an uploaded image; returns a path relative to /static."""
    if file_storage is None or not file_storage.filename:
        raise UploadError("No file selected.")
    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if ext not in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]:
        raise UploadError("Upload a PNG, JPG or WebP image.")

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > current_app.config["MAX_IMAGE_BYTES"]:
        raise UploadError(f"Images must be smaller than {current_app.config['MAX_IMAGE_BYTES'] // (1024 * 1024)} MB.")

    try:
        with Image.open(file_storage.stream) as probe:
            probe.verify()
        file_storage.stream.seek(0)
        image = Image.open(file_storage.stream)
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise UploadError("That file is not a valid image.") from exc

    has_alpha = image.mode in ("RGBA", "LA", "P")
    image = image.convert("RGBA" if has_alpha else "RGB")
    image.thumbnail(MAX_DIMENSIONS.get(kind, MAX_DIMENSIONS["image"]))

    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], subdir)
    os.makedirs(folder, exist_ok=True)
    out_ext = "png" if has_alpha else "jpg"
    filename = f"{uuid.uuid4().hex}.{out_ext}"
    target = os.path.join(folder, filename)
    if out_ext == "png":
        image.save(target, "PNG", optimize=True)
    else:
        image.save(target, "JPEG", quality=85, optimize=True, progressive=True)
    return f"uploads/{subdir}/{filename}".replace("\\", "/")


def delete_image(relative_path):
    """Remove a previously uploaded file (only ever inside the uploads folder)."""
    if not relative_path or not relative_path.startswith("uploads/"):
        return
    root = os.path.realpath(current_app.config["UPLOAD_FOLDER"])
    target = os.path.realpath(os.path.join(current_app.static_folder, relative_path))
    if target.startswith(root + os.sep) and os.path.isfile(target):
        os.remove(target)
