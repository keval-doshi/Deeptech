"""Image and document upload handling.

Uploads are validated by extension, size and actual decoded content, then
re-encoded with Pillow. Re-encoding strips metadata (EXIF/GPS) and defeats
polyglot files. Filenames are random, so user input never reaches the path.

Proof documents (PDF or image) are stored privately under PROOF_FOLDER, never
under /static, and are only ever served as downloads to authorised users.
"""
import os
import uuid

from flask import current_app
from PIL import Image, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 40_000_000  # decompression-bomb guard

MAX_DIMENSIONS = {"logo": (512, 512), "cover": (1920, 1080), "photo": (600, 600), "image": (1600, 1200),
                  "document": (2400, 2400)}
DOCUMENT_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp"}


class UploadError(ValueError):
    pass


def _extension(file_storage):
    name = file_storage.filename or ""
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _size(file_storage):
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    return size


def save_image(file_storage, subdir, kind="image"):
    """Validate and store an uploaded image; returns a path relative to /static."""
    if file_storage is None or not file_storage.filename:
        raise UploadError("No file selected.")
    if _extension(file_storage) not in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]:
        raise UploadError("Upload a PNG, JPG or WebP image.")
    if _size(file_storage) > current_app.config["MAX_IMAGE_BYTES"]:
        raise UploadError(f"Images must be smaller than {current_app.config['MAX_IMAGE_BYTES'] // (1024 * 1024)} MB.")
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], subdir)
    filename = _store_image(file_storage, folder, kind)
    return f"uploads/{subdir}/{filename}".replace("\\", "/")


def _store_image(file_storage, folder, kind):
    """Decode, re-encode and save an image into `folder`; returns the new filename."""
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

    os.makedirs(folder, exist_ok=True)
    out_ext = "png" if has_alpha else "jpg"
    filename = f"{uuid.uuid4().hex}.{out_ext}"
    target = os.path.join(folder, filename)
    if out_ext == "png":
        image.save(target, "PNG", optimize=True)
    else:
        image.save(target, "JPEG", quality=85, optimize=True, progressive=True)
    return filename


def delete_image(relative_path):
    """Remove a previously uploaded file (only ever inside the uploads folder)."""
    if not relative_path or not relative_path.startswith("uploads/"):
        return
    root = os.path.realpath(current_app.config["UPLOAD_FOLDER"])
    target = os.path.realpath(os.path.join(current_app.static_folder, relative_path))
    if target.startswith(root + os.sep) and os.path.isfile(target):
        os.remove(target)


# --------------------------------------------------------------------------
# Private proof documents
# --------------------------------------------------------------------------

def save_proof_document(file_storage, subdir):
    """Validate and privately store a proof document (PDF or image).

    Returns a path relative to PROOF_FOLDER. PDFs are checked for a PDF
    header and stored as-is; images are re-encoded like every other image.
    """
    if file_storage is None or not file_storage.filename:
        raise UploadError("Upload a document that proves your company is registered.")
    ext = _extension(file_storage)
    if ext not in DOCUMENT_EXTENSIONS:
        raise UploadError("Upload a PDF, PNG, JPG or WebP file.")
    limit = current_app.config["MAX_DOCUMENT_BYTES"]
    if _size(file_storage) > limit:
        raise UploadError(f"Documents must be smaller than {limit // (1024 * 1024)} MB.")

    folder = os.path.join(current_app.config["PROOF_FOLDER"], subdir)
    if ext == "pdf":
        data = file_storage.stream.read()
        if not data.startswith(b"%PDF-"):
            raise UploadError("That file is not a valid PDF.")
        os.makedirs(folder, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.pdf"
        with open(os.path.join(folder, filename), "wb") as out:
            out.write(data)
    else:
        filename = _store_image(file_storage, folder, "document")
    return f"{subdir}/{filename}".replace("\\", "/")


def proof_document_abspath(relative_path):
    """Absolute path of a stored proof document, or None if it is missing or outside PROOF_FOLDER."""
    if not relative_path:
        return None
    root = os.path.realpath(current_app.config["PROOF_FOLDER"])
    target = os.path.realpath(os.path.join(root, relative_path))
    if target.startswith(root + os.sep) and os.path.isfile(target):
        return target
    return None


def delete_proof_document(relative_path):
    target = proof_document_abspath(relative_path)
    if target:
        os.remove(target)
