"""Bounded validation for untrusted .builderplugin ZIP packages."""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import stat
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from builder_hub.plugins.protocol import (
	ALLOWED_SUFFIXES,
	MAX_EXTRACTED_SIZE,
	MAX_FILE_SIZE,
	MAX_ICON_SIZE,
	MAX_PACKAGE_FILES,
	MAX_PACKAGE_SIZE,
	PACKAGE_FOLDERS,
	ProtocolValidationError,
	validate_manifest,
)

EXTERNAL_SVG_REFERENCE = re.compile(
	r"(?:url\s*\(\s*['\"]?\s*(?!#)|^\s*(?:https?:|//|data:|javascript:))", re.I
)
# animate and set can assign a javascript: URL to href after validation
FORBIDDEN_SVG_ELEMENTS = {"script", "foreignobject", "animate", "set"}


@dataclass(frozen=True)
class ValidatedPackage:
	manifest: dict
	package_sha256: str
	package_size: int
	icon_content: bytes | None


def validate_package(
	package_path: str | os.PathLike,
	*,
	expected_name: str,
	expected_version: str,
) -> ValidatedPackage:
	path = Path(package_path)
	package_size = path.stat().st_size
	if package_size > MAX_PACKAGE_SIZE:
		raise ProtocolValidationError("package_too_large", "The compressed package exceeds 10 MB.")

	package_sha256 = sha256(path)
	try:
		with zipfile.ZipFile(path) as archive:
			entries = inspect_archive(archive)
			manifest = read_manifest(archive, entries)
			validate_package_files(entries, manifest.get("icon"))
			validate_package_identity(manifest, expected_name, expected_version)
			svgs = read_validated_svgs(archive, entries)
	# //// Neoffice — parenthesized: `except A, B:` is Python 3.14 only (PEP 758) and our servers run 3.12; identical on 3.14. Remove when the fleet runs 3.14.
	except (zipfile.BadZipFile, zlib.error, NotImplementedError, EOFError):
		raise ProtocolValidationError("invalid_zip", "The plugin package is not a valid ZIP file.")

	return ValidatedPackage(manifest, package_sha256, package_size, svgs.get(manifest.get("icon")))


def validate_svg(content: bytes, name: str = "SVG") -> None:
	if len(content) > MAX_ICON_SIZE:
		raise ProtocolValidationError("unsafe_svg", f"{name} is too large.")
	text = decode_svg(content, name)
	root = parse_svg(text, name)
	if local_name(root.tag).lower() != "svg":
		raise ProtocolValidationError("unsafe_svg", f"{name} does not have an SVG root element.")
	for element in root.iter():
		validate_svg_element(element, name)


def decode_svg(content: bytes, name: str) -> str:
	try:
		return content.decode("utf-8", errors="strict")
	except UnicodeDecodeError:
		raise ProtocolValidationError("unsafe_svg", f"{name} is not valid UTF-8 SVG.")


def parse_svg(text: str, name: str) -> ET.Element:
	if re.search(r"<!DOCTYPE|<!ENTITY", text, flags=re.I):
		raise ProtocolValidationError("unsafe_svg", f"{name} contains a forbidden declaration.")
	if re.search(r"<\?xml-stylesheet|@import", text, flags=re.I) or EXTERNAL_SVG_REFERENCE.search(text):
		raise ProtocolValidationError("unsafe_svg", f"{name} contains an external reference.")
	try:
		return ET.fromstring(text)
	# //// Neoffice — parenthesized: `except A, B:` is Python 3.14 only (PEP 758) and our servers run 3.12; identical on 3.14. Remove when the fleet runs 3.14.
	except (ET.ParseError, UnicodeDecodeError):
		raise ProtocolValidationError("unsafe_svg", f"{name} is not valid UTF-8 SVG.")


def validate_svg_element(element: ET.Element, name: str) -> None:
	tag = local_name(element.tag).lower()
	if tag in FORBIDDEN_SVG_ELEMENTS:
		raise ProtocolValidationError("unsafe_svg", f"{name} contains a forbidden {tag} element.")
	for attribute, value in element.attrib.items():
		attribute = local_name(attribute).lower()
		value = value.strip()
		if attribute.startswith("on"):
			raise ProtocolValidationError("unsafe_svg", f"{name} contains an event attribute.")
		if attribute in {"href", "src"} and value and not value.startswith("#"):
			raise ProtocolValidationError("unsafe_svg", f"{name} contains an external reference.")
		if EXTERNAL_SVG_REFERENCE.search(value):
			raise ProtocolValidationError("unsafe_svg", f"{name} contains an external reference.")


def inspect_archive(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
	infos = archive.infolist()
	if len(infos) > MAX_PACKAGE_FILES:
		raise ProtocolValidationError(
			"too_many_files", f"The package contains more than {MAX_PACKAGE_FILES} entries."
		)

	entries: dict[str, zipfile.ZipInfo] = {}
	extracted_size = 0
	for entry in infos:
		normalized = normalized_path(entry.filename)
		if entry.is_dir():
			continue
		validate_file_entry(entry, normalized, entries)
		extracted_size += entry.file_size
		if extracted_size > MAX_EXTRACTED_SIZE:
			raise ProtocolValidationError("package_too_large", "The extracted package exceeds 30 MB.")
		entries[normalized] = entry

	for required in ("manifest.json", "main.js"):
		if required not in entries:
			raise ProtocolValidationError("missing_required_file", f"The package is missing {required}.")
	return entries


def validate_package_files(entries: dict[str, zipfile.ZipInfo], icon_name: str | None) -> None:
	if icon_name and icon_name not in entries:
		raise ProtocolValidationError("missing_icon", "The manifest icon is missing from the package.")
	root_files = {"manifest.json", "main.js"}
	if icon_name:
		root_files.add(icon_name)
	for name in sorted(entries):
		parts = PurePosixPath(name).parts
		if name not in root_files and not (len(parts) > 1 and parts[0] in PACKAGE_FOLDERS):
			raise ProtocolValidationError(
				"unexpected_file", f"The package contains an unexpected file: {name}."
			)


def validate_file_entry(
	entry: zipfile.ZipInfo,
	normalized: str,
	existing_entries: dict[str, zipfile.ZipInfo],
) -> None:
	if is_symlink(entry):
		raise ProtocolValidationError("symlink", f"ZIP entry is a symbolic link: {entry.filename}.")
	if normalized in existing_entries:
		raise ProtocolValidationError("duplicate_path", f"ZIP contains duplicate path: {normalized}.")
	if entry.flag_bits & 0x1:
		raise ProtocolValidationError(
			"encrypted_file", f"Encrypted ZIP entry is not allowed: {entry.filename}."
		)
	if Path(normalized).suffix not in ALLOWED_SUFFIXES:
		raise ProtocolValidationError("unsupported_file", f"Unsupported package file: {normalized}.")
	if entry.file_size > MAX_FILE_SIZE:
		raise ProtocolValidationError("file_too_large", f"Package file is too large: {normalized}.")


def normalized_path(name: str) -> str:
	if "\x00" in name:
		raise ProtocolValidationError("unsafe_path", "A ZIP path contains a null byte.")
	name = unicodedata.normalize("NFC", name.replace("\\", "/"))
	path = PurePosixPath(name)
	if (
		path.is_absolute()
		or ".." in path.parts
		or not name
		or name.startswith("/")
		or re.match(r"^[A-Za-z]:/", name)
	):
		raise ProtocolValidationError("unsafe_path", f"Unsafe ZIP path: {name}.")
	normalized = posixpath.normpath(name)
	if normalized in {".", ".."} or normalized.startswith("../"):
		raise ProtocolValidationError("unsafe_path", f"Unsafe ZIP path: {name}.")
	return normalized


def is_symlink(entry: zipfile.ZipInfo) -> bool:
	return stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFLNK


def read_manifest(archive: zipfile.ZipFile, entries: dict[str, zipfile.ZipInfo]) -> dict:
	content = read_entry(archive, entries["manifest.json"], 128 * 1024)
	try:
		manifest = json.loads(content.decode("utf-8"))
	# //// Neoffice — parenthesized: `except A, B:` is Python 3.14 only (PEP 758) and our servers run 3.12; identical on 3.14. Remove when the fleet runs 3.14.
	except (UnicodeDecodeError, json.JSONDecodeError):
		raise ProtocolValidationError("invalid_manifest_json", "manifest.json must contain valid UTF-8 JSON.")
	return validate_manifest(manifest)


def validate_package_identity(manifest: dict, expected_name: str, expected_version: str) -> None:
	if manifest["name"] != expected_name:
		raise ProtocolValidationError(
			"identity_mismatch", "The package manifest name does not match the plugin listing."
		)
	if manifest["version"] != expected_version:
		raise ProtocolValidationError(
			"version_mismatch", "The package manifest version does not match the GitHub release."
		)


def read_validated_svgs(archive: zipfile.ZipFile, entries: dict[str, zipfile.ZipInfo]) -> dict[str, bytes]:
	"""Every SVG, not only the icon: Builder serves them all from the site's origin."""
	svgs = {}
	for name, entry in entries.items():
		if name.endswith(".svg"):
			svgs[name] = read_entry(archive, entry, MAX_ICON_SIZE, code="unsafe_svg")
			validate_svg(svgs[name], name)
	return svgs


def read_entry(
	archive: zipfile.ZipFile,
	entry: zipfile.ZipInfo,
	limit: int,
	*,
	code: str = "entry_too_large",
) -> bytes:
	with archive.open(entry) as source:
		content = source.read(limit + 1)
	if len(content) > limit:
		raise ProtocolValidationError(code, f"Package file is too large: {entry.filename}.")
	return content


def sha256(path: Path) -> str:
	digest = hashlib.sha256()
	with path.open("rb") as package:
		for chunk in iter(lambda: package.read(1024 * 1024), b""):
			digest.update(chunk)
	return digest.hexdigest()


def local_name(name: str) -> str:
	return name.rsplit("}", 1)[-1]
