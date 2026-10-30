"""Versioned Builder plugin protocol constants and value validation."""

from __future__ import annotations

import re
from collections.abc import Mapping

PROTOCOL_VERSION = 1

MAX_PACKAGE_SIZE = 10 * 1024 * 1024
MAX_EXTRACTED_SIZE = 30 * 1024 * 1024
MAX_FILE_SIZE = 5 * 1024 * 1024
MAX_PACKAGE_FILES = 200
MAX_ICON_SIZE = 64 * 1024

CATALOG_PAGE_SIZE = 100

PLUGIN_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*$")
SEMVER_PATTERN = re.compile(
	r"^(0|[1-9]\d*)\."
	r"(0|[1-9]\d*)\."
	r"(0|[1-9]\d*)"
	r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
	r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
	r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)

# The files the editor loads from a package. Keep in step with
# `ASSET_TYPES` in `builder/plugins/constants.py`. No HTML or XML.
ALLOWED_SUFFIXES = frozenset(
	{
		".js",
		".css",
		".json",
		".svg",
		".png",
		".jpg",
		".jpeg",
		".gif",
		".webp",
		".woff",
		".woff2",
	}
)

# Build output folders beside the root files. The entry imports these by relative path.
PACKAGE_FOLDERS = frozenset({"chunks", "assets"})

# Keep in step with `MANIFEST_REQUIRED_FIELDS` in `builder/plugins/package.py`.
MANIFEST_V1_REQUIRED_FIELDS = frozenset({"v", "name", "label", "description", "version", "entry"})
MANIFEST_V1_OPTIONAL_FIELDS = frozenset({"icon"})
MANIFEST_V1_FIELDS = MANIFEST_V1_REQUIRED_FIELDS | MANIFEST_V1_OPTIONAL_FIELDS


class ProtocolValidationError(ValueError):
	"""A stable, author-visible protocol validation failure."""

	def __init__(self, code: str, message: str):
		super().__init__(message)
		self.code = code
		self.message = message

	def as_dict(self) -> dict[str, str]:
		return {"code": self.code, "message": self.message}


def validate_manifest(manifest: object) -> dict:
	if not isinstance(manifest, Mapping):
		raise ProtocolValidationError("manifest_not_object", "manifest.json must contain a JSON object.")

	manifest = dict(manifest)
	validate_manifest_fields(manifest)
	validate_manifest_identity(manifest)
	validate_manifest_icon(manifest.get("icon"))
	return manifest


def validate_manifest_fields(manifest: dict) -> None:
	missing = sorted(MANIFEST_V1_REQUIRED_FIELDS - manifest.keys())
	if missing:
		raise ProtocolValidationError(
			"manifest_missing_field", f"manifest.json is missing required field: {missing[0]}."
		)

	unknown = sorted(manifest.keys() - MANIFEST_V1_FIELDS)
	if unknown:
		raise ProtocolValidationError(
			"manifest_unknown_field", f"manifest.json contains unsupported field: {unknown[0]}."
		)

	if type(manifest["v"]) is not int or manifest["v"] != PROTOCOL_VERSION:
		raise ProtocolValidationError(
			"unsupported_protocol", f"Manifest protocol v must equal {PROTOCOL_VERSION}."
		)


def validate_manifest_identity(manifest: dict) -> None:
	name = manifest["name"]
	if not isinstance(name, str) or not PLUGIN_NAME_PATTERN.fullmatch(name):
		raise ProtocolValidationError("invalid_name", "Manifest name must use the publisher/name format.")

	validate_plain_text(manifest["label"], "label", 80)
	validate_plain_text(manifest["description"], "description", 240)

	version = manifest["version"]
	if not isinstance(version, str) or not SEMVER_PATTERN.fullmatch(version):
		raise ProtocolValidationError("invalid_version", "Manifest version must be a valid SemVer value.")

	if manifest["entry"] != "main.js":
		raise ProtocolValidationError("invalid_entry", "Manifest entry must equal main.js.")


def validate_manifest_icon(icon: object) -> None:
	if icon is None:
		return
	if not isinstance(icon, str) or not icon or "/" in icon or "\\" in icon or not icon.endswith(".svg"):
		raise ProtocolValidationError("invalid_icon", "Manifest icon must name one root SVG file.")


def version_from_tag(tag: object) -> str | None:
	"""The SemVer version a release tag names, with or without a leading `v`."""
	if not isinstance(tag, str):
		return None
	version = tag.removeprefix("v")
	return version if SEMVER_PATTERN.fullmatch(version) else None


def semver_key(version: str) -> tuple:
	"""A deterministic SemVer precedence key; build metadata does not affect precedence."""
	match = SEMVER_PATTERN.fullmatch(version)
	if not match:
		raise ValueError(f"Invalid SemVer: {version}")
	major, minor, patch, prerelease, _build = match.groups()
	if prerelease is None:
		pre_key = (1,)
	else:
		parts = []
		for part in prerelease.split("."):
			parts.append((0, int(part)) if part.isdigit() else (1, part))
		pre_key = (0, *parts)
	return int(major), int(minor), int(patch), pre_key


def expected_package_name(plugin_name: str, version: str) -> str:
	return f"{plugin_name.replace('/', '-')}-{version}.builderplugin"


def validate_plain_text(value: object, fieldname: str, maximum: int) -> None:
	if not isinstance(value, str) or not 1 <= len(value) <= maximum or value != value.strip():
		raise ProtocolValidationError(
			f"invalid_{fieldname}", f"Manifest {fieldname} must contain 1 through {maximum} characters."
		)
	if (
		any(ord(character) < 32 and character not in "\t\n\r" for character in value)
		or "<" in value
		or ">" in value
	):
		raise ProtocolValidationError(
			f"invalid_{fieldname}", f"Manifest {fieldname} must contain plain text only."
		)
