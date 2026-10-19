"""Small, explicit server-side validators for form and JSON input."""
import re
import unicodedata
from datetime import date

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
URL_RE = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.IGNORECASE)
LINKEDIN_RE = re.compile(r"^https://([a-z]{2,3}\.)?linkedin\.com/", re.IGNORECASE)


class ValidationError(ValueError):
    def __init__(self, errors):
        super().__init__("Invalid input")
        self.errors = errors  # {field: message}


class Validator:
    """Collects errors across fields so forms can show them all at once."""

    def __init__(self, data):
        self.data = data or {}
        self.errors = {}
        self.clean = {}

    def _raw(self, field):
        value = self.data.get(field)
        if isinstance(value, str):
            value = value.strip()
        return value

    def text(self, field, label, required=True, min_len=0, max_len=255, multiline=False):
        value = self._raw(field)
        if value in (None, ""):
            if required:
                self.errors[field] = f"{label} is required."
            self.clean[field] = "" if not required else None
            return self
        if not isinstance(value, str):
            self.errors[field] = f"{label} must be text."
            return self
        if not multiline:
            value = " ".join(value.split())
        if len(value) < min_len:
            self.errors[field] = f"{label} must be at least {min_len} characters."
        elif len(value) > max_len:
            self.errors[field] = f"{label} must be at most {max_len} characters."
        self.clean[field] = value
        return self

    def email(self, field, label="Email", required=True):
        self.text(field, label, required=required, max_len=255)
        value = self.clean.get(field)
        if value and field not in self.errors:
            if not EMAIL_RE.match(value):
                self.errors[field] = "Enter a valid email address."
            self.clean[field] = value.lower()
        return self

    def url(self, field, label, required=False, linkedin=False):
        self.text(field, label, required=required, max_len=255)
        value = self.clean.get(field)
        if value and field not in self.errors:
            if not value.lower().startswith(("http://", "https://")):
                value = "https://" + value
            if not URL_RE.match(value):
                self.errors[field] = f"Enter a valid {label.lower()} URL."
            elif linkedin and not LINKEDIN_RE.match(value):
                self.errors[field] = "Enter a linkedin.com profile URL."
            self.clean[field] = value
        return self

    def integer(self, field, label, required=False, min_value=None, max_value=None):
        value = self._raw(field)
        if value in (None, ""):
            if required:
                self.errors[field] = f"{label} is required."
            self.clean[field] = None
            return self
        try:
            number = int(str(value).replace(",", ""))
        except (TypeError, ValueError):
            self.errors[field] = f"{label} must be a whole number."
            return self
        if min_value is not None and number < min_value:
            self.errors[field] = f"{label} must be at least {min_value:,}."
        elif max_value is not None and number > max_value:
            self.errors[field] = f"{label} must be at most {max_value:,}."
        self.clean[field] = number
        return self

    def choice(self, field, label, choices, required=True):
        value = self._raw(field)
        if value in (None, ""):
            if required:
                self.errors[field] = f"Select a {label.lower()}."
            self.clean[field] = None
            return self
        if value not in choices:
            self.errors[field] = f"Select a valid {label.lower()}."
        self.clean[field] = value
        return self

    def boolean(self, field):
        value = self.data.get(field)
        self.clean[field] = value in (True, "true", "on", "1", 1, "yes")
        return self

    def password(self, field="password", confirm_field=None):
        value = self.data.get(field) or ""
        if len(value) < 10:
            self.errors[field] = "Use at least 10 characters."
        elif len(value) > 128:
            self.errors[field] = "Use at most 128 characters."
        elif value.isdigit() or value.isalpha():
            self.errors[field] = "Mix letters with numbers or symbols."
        if confirm_field and value != (self.data.get(confirm_field) or ""):
            self.errors[confirm_field] = "Passwords do not match."
        self.clean[field] = value
        return self

    def check(self):
        if self.errors:
            raise ValidationError(self.errors)
        return self.clean


def year_bounds():
    return 1950, date.today().year


def slugify(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value[:80] or "startup"


def like_escape(term):
    """Escape LIKE wildcards in user search input."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
