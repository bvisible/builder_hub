"""A bounded GitHub client for plugin repository and release reads."""

from __future__ import annotations

import base64
import ipaddress
import json
import socket
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import frappe
import requests

from builder_hub.plugins.protocol import (
	MAX_PACKAGE_SIZE,
	ProtocolValidationError,
	validate_manifest,
)

API_ROOT = "https://api.github.com"
API_RESPONSE_LIMIT = 2 * 1024 * 1024
CONTENT_RESPONSE_LIMIT = 1024 * 1024
CONNECT_TIMEOUT = 5
RESPONSE_TIMEOUT = 20
MAX_REDIRECTS = 3
ASSET_HOSTS = frozenset(
	{
		"github.com",
		"objects.githubusercontent.com",
		"release-assets.githubusercontent.com",
		"github-releases.githubusercontent.com",
	}
)


@dataclass(frozen=True)
class GitHubResponse:
	data: Any
	etag: str | None
	status_code: int


class GitHubClient:
	def __init__(self, token: str | None = None, session: requests.Session | None = None):
		self.token = token if token is not None else configured_token()
		if not self.token and not frappe.conf.developer_mode:
			raise ProtocolValidationError(
				"github_token_missing",
				"Builder Hub cannot read GitHub because builder_hub_github_token is not set in the site config.",
			)
		self.session = session or requests.Session()

	def get_repository(self, repository_id: str) -> dict:
		return self.api_json(
			f"/repositories/{quote(str(repository_id), safe='')}",
			not_found=f"GitHub repository {repository_id} was not found. It was deleted or made private.",
		).data

	def get_repository_by_name(self, owner: str, name: str) -> dict:
		return self.api_json(
			f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}",
			not_found=f"GitHub repository {owner}/{name} was not found. Check the URL, and make sure the repository is public.",
		).data

	def get_repository_file(self, repository: dict, path: str) -> bytes:
		response = self.api_json(
			f"{repository_path(repository)}/contents/{quote(path, safe='/')}",
			limit=CONTENT_RESPONSE_LIMIT,
			not_found=f"The repository has no {path} file at the root of its default branch.",
		)
		data = response.data
		if not isinstance(data, dict) or data.get("type") != "file" or data.get("encoding") != "base64":
			raise ProtocolValidationError(
				"missing_repository_file", f"Required repository file is missing: {path}."
			)
		try:
			encoded = "".join((data.get("content") or "").split())
			content = base64.b64decode(encoded, validate=True)
		# //// Neoffice — parenthesized: `except A, B:` is Python 3.14 only (PEP 758) and our servers run 3.12; identical on 3.14. Remove when the fleet runs 3.14.
		except (ValueError, TypeError):
			raise ProtocolValidationError(
				"invalid_repository_file", f"GitHub returned invalid content for {path}."
			)
		if len(content) > CONTENT_RESPONSE_LIMIT:
			raise ProtocolValidationError(
				"repository_file_too_large", f"Repository file is too large: {path}."
			)
		return content

	def get_release(self, repository: dict, version: str) -> dict:
		for tag in (version, f"v{version}"):
			try:
				return self.api_json(
					f"{repository_path(repository)}/releases/tags/{quote(tag, safe='')}",
					not_found=f"The repository has no published GitHub release with the tag {version} or v{version}. Publish a release for the version in manifest.json, then submit again.",
				).data
			except ProtocolValidationError as error:
				if error.code != "github_not_found" or tag != version:
					raise

	def get_releases(self, repository: dict, etag: str | None = None) -> GitHubResponse:
		return self.api_json(
			f"{repository_path(repository)}/releases?per_page=100",
			etag=etag,
			allow_not_modified=True,
			not_found=f"GitHub repository {repository['owner']['login']}/{repository['name']} was not found.",
		)

	def download_asset(self, url: str) -> str:
		current_url = url
		temporary = tempfile.NamedTemporaryFile(prefix="builderplugin-", suffix=".builderplugin", delete=False)
		path = temporary.name
		try:
			with temporary:
				for redirect in range(MAX_REDIRECTS + 1):
					response = self.get_asset_response(current_url)
					try:
						next_url = get_redirect_url(response, redirect)
						if next_url:
							current_url = next_url
							continue
						validate_asset_response(response)
						temporary.writelines(
							iter_limited_chunks(
								response, MAX_PACKAGE_SIZE, "package_too_large", "package_download_failed"
							)
						)
						return path
					finally:
						response.close()
		except requests.RequestException:
			Path(path).unlink(missing_ok=True)
			raise ProtocolValidationError(
				"package_download_failed", "GitHub package download could not be completed."
			)
		except Exception:
			Path(path).unlink(missing_ok=True)
			raise

	def get_asset_response(self, url: str):
		validate_asset_url(url)
		headers = self.get_headers(auth=urlparse(url).hostname == "github.com")
		return self.session.get(
			url,
			headers=headers,
			stream=True,
			allow_redirects=False,
			timeout=(CONNECT_TIMEOUT, RESPONSE_TIMEOUT),
		)

	def api_json(
		self,
		path: str,
		*,
		etag: str | None = None,
		allow_not_modified: bool = False,
		limit: int = API_RESPONSE_LIMIT,
		not_found: str = "GitHub could not find the requested resource.",
	) -> GitHubResponse:
		url = f"{API_ROOT}{path}"
		headers = self.get_headers(auth=True)
		if etag:
			headers["If-None-Match"] = etag
		response = self.get_api_response(url, headers)
		try:
			if response.status_code == 304 and allow_not_modified:
				return GitHubResponse(None, etag, 304)
			validate_api_response(response, not_found, has_token=bool(self.token))
			content = b"".join(
				iter_limited_chunks(response, limit, "github_response_too_large", "github_request_failed")
			)
			response_etag = response.headers.get("ETag")
			status_code = response.status_code
		finally:
			response.close()
		return GitHubResponse(decode_api_json(content), response_etag, status_code)

	def get_api_response(self, url: str, headers: dict[str, str]):
		try:
			return self.session.get(
				url,
				headers=headers,
				allow_redirects=False,
				stream=True,
				timeout=(CONNECT_TIMEOUT, RESPONSE_TIMEOUT),
			)
		except requests.RequestException:
			raise ProtocolValidationError(
				"github_request_failed", "GitHub API request could not be completed."
			)

	def get_headers(self, *, auth: bool) -> dict[str, str]:
		headers = {
			"Accept": "application/vnd.github+json",
			"User-Agent": "Builder-Hub-Plugins/1",
			"X-GitHub-Api-Version": "2022-11-28",
		}
		if auth and self.token:
			headers["Authorization"] = f"Bearer {self.token}"
		return headers


def get_redirect_url(response, redirect: int) -> str | None:
	if not response.is_redirect:
		return None
	if redirect == MAX_REDIRECTS:
		raise ProtocolValidationError("too_many_redirects", "Package download used too many redirects.")
	return response.headers.get("Location", "")


def validate_asset_response(response) -> None:
	if response.status_code != 200:
		raise ProtocolValidationError(
			"package_download_failed",
			f"GitHub package download failed with HTTP {response.status_code}.",
		)


def validate_api_response(response, not_found: str, *, has_token: bool) -> None:
	if is_rate_limited(response):
		message = "Builder Hub reached its GitHub API rate limit. Try again later."
		if not has_token:
			message += " Set builder_hub_github_token in the site config to raise the limit."
		raise ProtocolValidationError("github_rate_limited", message)
	# its own code, so an optional file can tell "not there" from "GitHub failed"
	if response.status_code == 404:
		raise ProtocolValidationError("github_not_found", not_found)
	if response.status_code == 401:
		raise ProtocolValidationError(
			"github_request_failed",
			"GitHub rejected builder_hub_github_token. Replace it with a valid token.",
		)
	if response.status_code == 403:
		raise ProtocolValidationError("github_request_failed", "GitHub refused access to this repository.")
	if response.status_code >= 500:
		raise ProtocolValidationError(
			"github_request_failed",
			f"GitHub is unavailable (HTTP {response.status_code}). Try again later.",
		)
	if response.status_code != 200:
		raise ProtocolValidationError(
			"github_request_failed", f"GitHub API request failed with HTTP {response.status_code}."
		)


def is_rate_limited(response) -> bool:
	# GitHub sends 403 or 429 for its primary and secondary rate limits
	if response.status_code == 429:
		return True
	return response.status_code == 403 and (
		response.headers.get("X-RateLimit-Remaining") == "0" or "Retry-After" in response.headers
	)


def iter_limited_chunks(response, limit: int, size_error_code: str, request_error_code: str):
	validate_content_length(response, limit, size_error_code)
	total = 0
	try:
		for chunk in response.iter_content(chunk_size=64 * 1024):
			if not chunk:
				continue
			total += len(chunk)
			if total > limit:
				raise ProtocolValidationError(size_error_code, "GitHub response exceeded its size limit.")
			yield chunk
	except requests.RequestException:
		raise ProtocolValidationError(request_error_code, "GitHub response could not be read.")


def validate_content_length(response, limit: int, error_code: str) -> None:
	length = response.headers.get("Content-Length")
	if not length:
		return
	try:
		too_large = int(length) > limit
	except ValueError:
		raise ProtocolValidationError("invalid_github_response", "GitHub returned an invalid response size.")
	if too_large:
		raise ProtocolValidationError(error_code, "GitHub response exceeded its size limit.")


def decode_api_json(content: bytes):
	try:
		return json.loads(content)
	except json.JSONDecodeError:
		raise ProtocolValidationError("invalid_github_response", "GitHub API returned invalid JSON.")


def validate_repository(repository: dict, publisher_account_id: str) -> None:
	validate_public_repository(repository)
	owner = repository.get("owner") or {}
	if str(owner.get("id")) != str(publisher_account_id):
		raise ProtocolValidationError(
			"repository_owner_mismatch",
			"The repository owner does not match the registered publisher account.",
		)


def validate_public_repository(repository: dict) -> None:
	"""Require a public, active GitHub repository with a default branch."""
	if repository.get("private"):
		raise ProtocolValidationError("private_repository", "The GitHub repository must be public.")
	if repository.get("archived") or repository.get("disabled"):
		raise ProtocolValidationError("inactive_repository", "The GitHub repository must be active.")
	if not repository.get("default_branch"):
		raise ProtocolValidationError("invalid_repository", "The GitHub repository has no default branch.")


def get_validated_repository_url(repository: dict) -> str:
	url = repository.get("html_url") or ""
	if not url.startswith("https://github.com/"):
		raise ProtocolValidationError("invalid_repository", "GitHub returned an invalid repository URL.")
	return url


def get_repository_contract(client: GitHubClient, repository: dict, license_id: str) -> dict:
	files = get_required_repository_files(client, repository)
	try:
		manifest = validate_manifest(json.loads(files["manifest.json"].decode("utf-8")))
	# //// Neoffice — parenthesized: `except A, B:` is Python 3.14 only (PEP 758) and our servers run 3.12; identical on 3.14. Remove when the fleet runs 3.14.
	except (UnicodeDecodeError, json.JSONDecodeError):
		raise ProtocolValidationError(
			"invalid_repository_json", "Repository manifest.json must contain UTF-8 JSON."
		)
	validate_repository_license(repository, license_id, files["LICENSE"])
	readme = files["README.md"]
	return {
		"manifest": manifest,
		"readme": readme.decode("utf-8", errors="replace"),
	}


def parse_repository_url(url: str) -> tuple[str, str]:
	parsed = urlparse(url)
	parts = parsed.path.strip("/").split("/")
	if (
		parsed.scheme != "https"
		or parsed.hostname != "github.com"
		or len(parts) != 2
		or parsed.query
		or parsed.fragment
	):
		raise ProtocolValidationError(
			"invalid_repository_url", "Enter an HTTPS URL for one GitHub repository."
		)
	name = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
	return parts[0], name


def get_required_repository_files(client: GitHubClient, repository: dict) -> dict[str, bytes]:
	files = {}
	for name in ("manifest.json", "README.md", "LICENSE"):
		try:
			files[name] = client.get_repository_file(repository, name)
		except ProtocolValidationError as error:
			if error.code == "github_not_found":
				raise ProtocolValidationError("missing_repository_file", error.message)
			raise
	return files



def get_repository_license(repository: dict) -> str:
	license_id = (repository.get("license") or {}).get("spdx_id")
	if not license_id or license_id == "NOASSERTION":
		raise ProtocolValidationError(
			"license_mismatch", "The repository must declare a recognized SPDX license."
		)
	return license_id


def validate_repository_license(repository: dict, license_id: str, license_content: bytes) -> None:
	if get_repository_license(repository) != license_id:
		raise ProtocolValidationError(
			"license_mismatch", "The repository license does not match the submitted SPDX license ID."
		)
	if not license_content.strip():
		raise ProtocolValidationError("license_mismatch", "The repository LICENSE file is empty.")


def repository_path(repository: dict) -> str:
	return f"/repos/{quote(repository['owner']['login'], safe='')}/{quote(repository['name'], safe='')}"


def configured_token() -> str | None:
	return frappe.conf.get("builder_hub_github_token") or frappe.conf.get("github_token")


def validate_asset_url(url: str) -> None:
	parsed = urlparse(url)
	host = (parsed.hostname or "").lower().rstrip(".")
	if parsed.scheme != "https" or host not in ASSET_HOSTS or parsed.username or parsed.password:
		raise ProtocolValidationError(
			"unsafe_package_url", "The package URL is not an allowed GitHub asset URL."
		)
	try:
		addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
	except socket.gaierror:
		raise ProtocolValidationError("unsafe_package_url", "The package host could not be resolved.")
	if not addresses:
		raise ProtocolValidationError("unsafe_package_url", "The package host could not be resolved.")
	for address in addresses:
		ip = ipaddress.ip_address(address)
		if not ip.is_global:
			raise ProtocolValidationError(
				"unsafe_package_url", "The package host resolved to a private address."
			)
