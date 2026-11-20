import os
import re
import warnings
from io import BytesIO

from cryptography.fernet import Fernet, InvalidToken
from PIL import Image, ImageOps


MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


class DocumentProcessingUnavailable(RuntimeError):
    pass


class InvalidDocument(ValueError):
    pass


def sanitize_image(upload, max_bytes=MAX_DOCUMENT_BYTES):
    raw = upload.read(max_bytes + 1)
    if not raw:
        raise InvalidDocument("Choose a document image to upload.")
    if len(raw) > max_bytes:
        raise InvalidDocument("Each document image must be 4 MB or smaller.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as opened:
                if opened.format not in {"JPEG", "PNG"}:
                    raise InvalidDocument("Upload a JPEG or PNG document image.")
                opened.verify()
            with Image.open(BytesIO(raw)) as opened:
                image = ImageOps.exif_transpose(opened)
                image.load()
    except InvalidDocument:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise InvalidDocument("The image dimensions are too large.")
    except (OSError, ValueError):
        raise InvalidDocument("The uploaded file is not a valid JPEG or PNG image.")

    if image.width * image.height > MAX_IMAGE_PIXELS:
        raise InvalidDocument("The image dimensions are too large.")

    if image.mode in {"RGBA", "LA"}:
        alpha = image.getchannel("A")
        background = Image.new("RGB", image.size, "white")
        background.paste(image.convert("RGB"), mask=alpha)
        image = background
    else:
        image = image.convert("RGB")

    output = BytesIO()
    image.save(output, format="JPEG", quality=88, optimize=True)
    sanitized = output.getvalue()
    if len(sanitized) > max_bytes:
        raise InvalidDocument("The processed image is too large.")
    return sanitized, "image/jpeg"


def document_cipher():
    key = os.environ.get("APPLICATION_DOCUMENT_KEY", "").strip()
    if not key:
        raise DocumentProcessingUnavailable(
            "Application document encryption is not configured."
        )
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise DocumentProcessingUnavailable(
            "Application document encryption is misconfigured."
        )


def encrypt_document(cipher, content):
    return cipher.encrypt(content)


def decrypt_document(cipher, encrypted_content):
    try:
        return cipher.decrypt(encrypted_content)
    except InvalidToken:
        raise DocumentProcessingUnavailable(
            "This document cannot be decrypted with the configured key."
        )


def _ocr_text(image_bytes):
    try:
        import pytesseract
        from pytesseract import TesseractError, TesseractNotFoundError
    except ImportError:
        raise DocumentProcessingUnavailable(
            "Document OCR is unavailable; install the application dependencies."
        )

    executable = os.environ.get("TESSERACT_CMD")
    if executable:
        pytesseract.pytesseract.tesseract_cmd = executable
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            return pytesseract.image_to_string(
                image, lang="eng", config="--psm 6", timeout=20
            )
    except TesseractNotFoundError:
        raise DocumentProcessingUnavailable(
            "Document OCR is unavailable; install Tesseract OCR and configure TESSERACT_CMD if needed."
        )
    except TesseractError:
        raise DocumentProcessingUnavailable(
            "Document OCR could not process the uploaded image."
        )
    except RuntimeError:
        raise DocumentProcessingUnavailable(
            "Document OCR timed out; use a clearer or smaller image."
        )


def _normalized_name(value):
    return " ".join(re.findall(r"[A-Z0-9]+", value.upper()))


def _name_appears(name, text):
    expected = set(_normalized_name(name).split())
    observed = set(_normalized_name(text).split())
    return bool(expected) and expected.issubset(observed)


def _mrz_lines(text):
    lines = []
    for line in text.upper().replace("«", "<").splitlines():
        normalized = re.sub(r"[^A-Z0-9<]", "", line)
        if len(normalized) >= 44:
            for start in range(len(normalized) - 43):
                candidate = normalized[start : start + 44]
                if candidate.count("<") >= 1:
                    lines.append(candidate)
    for index, first in enumerate(lines[:-1]):
        second = lines[index + 1]
        if first.startswith("P<") and len(second) == 44:
            return first, second
    return None


def _mrz_check_digit(value):
    weights = (7, 3, 1)
    total = 0
    for index, character in enumerate(value):
        if character == "<":
            number = 0
        elif character.isdigit():
            number = int(character)
        elif "A" <= character <= "Z":
            number = ord(character) - ord("A") + 10
        else:
            return False
        total += number * weights[index % len(weights)]
    return total % 10


def parse_td3_mrz(text):
    lines = _mrz_lines(text)
    if not lines:
        return None
    first, second = lines
    checks = (
        (second[0:9], second[9]),
        (second[13:19], second[19]),
        (second[21:27], second[27]),
        (second[28:42], second[42]),
        (
            second[0:10] + second[13:20] + second[21:43],
            second[43],
        ),
    )
    valid = all(
        digit.isdigit() and _mrz_check_digit(field) == int(digit)
        for field, digit in checks
    )
    name_parts = first[5:].split("<<", 1)
    name = " ".join(
        part.replace("<", " ").strip()
        for part in name_parts
        if part.replace("<", " ").strip()
    )
    return {"valid": valid, "name": name}


def inspect_documents(identity_image, passport_image, applicant_name):
    identity_text = _ocr_text(identity_image)
    identity_readable = bool(identity_text.strip())
    result = {
        "identity_ocr_status": "readable" if identity_readable else "unreadable",
        "identity_name_status": (
            "matched"
            if identity_readable and _name_appears(applicant_name, identity_text)
            else "manual_review"
        ),
        "mrz_status": "not_provided",
        "mrz_name_status": "not_checked",
    }

    if passport_image is None:
        return result

    passport_text = _ocr_text(passport_image)
    mrz = parse_td3_mrz(passport_text)
    if mrz is None:
        result["mrz_status"] = "not_detected"
        result["mrz_name_status"] = "manual_review"
    else:
        result["mrz_status"] = "valid" if mrz["valid"] else "invalid"
        result["mrz_name_status"] = (
            "matched"
            if mrz["valid"] and _name_appears(applicant_name, mrz["name"])
            else "manual_review"
        )
    return result
