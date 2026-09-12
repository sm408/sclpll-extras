"""Azure Blob implementation of SCLPL's public resource-provider contract."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, BinaryIO
from urllib.parse import parse_qs, quote, urlsplit, urlunsplit

from sclpl.ext.api import (
    ResourceAuthenticationError,
    ResourceCapabilities,
    ResourceConflict,
    ResourceInfo,
    ResourceInvalidURI,
    ResourceNotFound,
    ResourcePermissionDenied,
    ResourceUnavailable,
    SclplError,
)


@dataclass(frozen=True, slots=True)
class AzureBlobURI:
    account: str
    container: str
    blob: str

    @property
    def account_url(self) -> str:
        return f"https://{self.account}.blob.core.windows.net"


@dataclass(slots=True)
class AzureBlobLease:
    """A native Azure blob lease exposed through the provider-neutral contract."""

    uri: str
    lease_id: str
    _lease: Any
    _provider: AzureBlobProvider
    _released: bool = False

    def release(self) -> None:
        if self._released:
            return
        try:
            self._lease.release()
        except Exception as error:
            raise self._provider._translate(error, self.uri) from error
        self._released = True

    def __enter__(self) -> AzureBlobLease:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback
        self.release()


def parse_uri(uri: str) -> AzureBlobURI:
    parsed = urlsplit(uri)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme.lower() != "azblob" or not parsed.netloc or not parts:
        raise ResourceInvalidURI("azblob URI must be azblob://<account>/<container>/<blob>")
    return AzureBlobURI(parsed.netloc, parts[0], "/".join(parts[1:]))


class AzureBlobProvider:
    scheme = "azblob"

    def __init__(
        self,
        *,
        environment: Mapping[str, str] | None = None,
        configuration: Mapping[str, Any] | None = None,
        credential_factory: Callable[[str], Any] | None = None,
    ) -> None:
        """Configure authentication without placing credentials in resource URIs.

        Hosts which own a custom Azure ``TokenCredential`` can provide it through
        ``credential_factory``. Command-line use is configured through the
        environment variables documented in ``docs/remote-resources.md``.
        """
        self._environment = environment if environment is not None else os.environ
        self._configuration = self._select_profile(configuration or {})
        self._credential_factory = credential_factory

    def capabilities(self) -> ResourceCapabilities:
        return ResourceCapabilities(
            write=True,
            list=True,
            revisions=True,
            conditional_write=True,
            locks=True,
            server_copy=True,
            resumable_downloads=True,
        )

    def normalize(self, uri: str) -> str:
        parsed = urlsplit(uri)
        details = parse_uri(uri)
        path = f"/{details.container}" + (f"/{details.blob}" if details.blob else "")
        return urlunsplit(("azblob", details.account.lower(), path, parsed.query, ""))

    def resolve(self, base_uri: str, reference: str) -> str:
        if "://" in reference:
            return self.normalize(reference)
        return self.normalize(f"{base_uri.rstrip('/')}/{reference.lstrip('/')}")

    def stat(self, uri: str) -> ResourceInfo:
        client = self._blob(uri)
        try:
            props = client.get_blob_properties()
        except Exception as error:  # Azure SDK is optional and translated here.
            raise self._translate(error, uri) from error
        return self._info(uri, props)

    def exists(self, uri: str) -> bool:
        try:
            return bool(self._blob(uri).exists())
        except Exception as error:
            mapped = self._translate(error, uri)
            if isinstance(mapped, ResourceNotFound):
                return False
            raise mapped from error

    def list(self, uri: str) -> Iterable[ResourceInfo]:
        details = parse_uri(uri)
        try:
            container = self._service(details.account).get_container_client(details.container)
            return [
                ResourceInfo(
                    uri=self.normalize(
                        f"azblob://{details.account}/{details.container}/{item.name}"
                    ),
                    size=getattr(item, "size", None),
                    modified=getattr(item, "last_modified", None),
                    revision=getattr(item, "etag", None),
                    content_type=getattr(
                        getattr(item, "content_settings", None), "content_type", None
                    ),
                    metadata=dict(getattr(item, "metadata", None) or {}),
                )
                for item in container.list_blobs(name_starts_with=details.blob)
            ]
        except Exception as error:
            raise self._translate(error, uri) from error

    def download(self, uri: str, target: BinaryIO) -> ResourceInfo:
        try:
            client = self._blob(uri)
            downloader = client.download_blob(**self._transfer_options())
            downloader.readinto(target)
            return self._info(uri, client.get_blob_properties())
        except Exception as error:
            raise self._translate(error, uri) from error

    def download_range(
        self,
        uri: str,
        target: BinaryIO,
        *,
        offset: int,
        expected_revision: str,
    ) -> ResourceInfo:
        """Continue a download only when the object still has the observed ETag."""
        try:
            from azure.core import MatchConditions

            client = self._blob(uri)
            downloader = client.download_blob(
                offset=offset,
                etag=expected_revision,
                match_condition=MatchConditions.IfNotModified,
                **self._transfer_options(),
            )
            downloader.readinto(target)
            return self._info(uri, client.get_blob_properties())
        except Exception as error:
            raise self._translate(error, uri) from error

    def upload(
        self,
        source: BinaryIO,
        uri: str,
        *,
        overwrite: bool = False,
        expected_revision: str | None = None,
    ) -> ResourceInfo:
        try:
            client = self._blob(uri)
            kwargs: dict[str, Any] = {"overwrite": overwrite}
            kwargs.update(self._transfer_options())
            if expected_revision is not None:
                from azure.core import MatchConditions

                kwargs.update(etag=expected_revision, match_condition=MatchConditions.IfNotModified)
            elif not overwrite:
                kwargs["overwrite"] = False
            client.upload_blob(source, **kwargs)
            return self._info(uri, client.get_blob_properties())
        except Exception as error:
            raise self._translate(error, uri) from error

    def acquire_lock(self, uri: str, *, lease_duration: int = 60) -> AzureBlobLease:
        """Acquire an Azure Blob lease for an existing blob."""
        if lease_duration != -1 and not 15 <= lease_duration <= 60:
            raise ResourceInvalidURI("Azure Blob lease_duration must be -1 or between 15 and 60")
        try:
            LeaseClient = self._lease_import()
            lease = LeaseClient(self._blob(uri))
            lease_id = lease.acquire(lease_duration=lease_duration)
            return AzureBlobLease(self.normalize(uri), str(lease_id), lease, self)
        except Exception as error:
            if isinstance(error, ResourceInvalidURI):
                raise
            raise self._translate(error, uri) from error

    def copy(
        self,
        source_uri: str,
        destination_uri: str,
        *,
        overwrite: bool = False,
        expected_revision: str | None = None,
    ) -> ResourceInfo:
        """Use Azure's service-side copy without downloading object bytes locally."""
        try:
            destination = self._blob(destination_uri)
            kwargs: dict[str, Any] = {}
            if expected_revision is not None:
                from azure.core import MatchConditions

                kwargs.update(etag=expected_revision, match_condition=MatchConditions.IfNotModified)
            elif not overwrite:
                kwargs["if_none_match"] = "*"
            destination.start_copy_from_url(self._copy_source_url(source_uri), **kwargs)
            return self._info(destination_uri, self._wait_for_copy(destination, destination_uri))
        except Exception as error:
            raise self._translate(error, destination_uri) from error

    def display_uri(self, uri: str) -> str:
        parsed = urlsplit(uri)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    def _service(self, account: str) -> Any:
        try:
            DefaultAzureCredential, BlobServiceClient, AzureSasCredential = self._imports()
        except ImportError as error:
            raise ResourceUnavailable("azblob requires: pip install sclpl-azure-blob") from error
        auth = self._setting("AUTH", default="default").lower().replace("_", "-")
        if auth == "connection-string":
            return BlobServiceClient.from_connection_string(
                self._secret("CONNECTION_STRING", "AZURE_STORAGE_CONNECTION_STRING")
            )

        account_url = self._account_url(account)
        if auth == "account-key":
            return BlobServiceClient(account_url, credential=self._secret("ACCOUNT_KEY"))
        if auth == "sas":
            if AzureSasCredential is None:
                raise ResourceUnavailable("azblob requires: pip install sclpl-azure-blob")
            return BlobServiceClient(
                account_url, credential=AzureSasCredential(self._secret("SAS_TOKEN").lstrip("?"))
            )
        if auth == "custom":
            if self._credential_factory is None:
                raise ResourceAuthenticationError(
                    "azblob custom authentication requires "
                    "AzureBlobProvider(credential_factory=...)"
                )
            return BlobServiceClient(account_url, credential=self._credential_factory(account))
        if auth != "default":
            raise ResourceAuthenticationError(
                "azblob SCLPL_AZURE_BLOB_AUTH must be one of: default, connection-string, "
                "account-key, sas, custom"
            )

        # Azure Identity itself selects Azure CLI/developer login, service-principal
        # environment credentials, workload identity, or managed identity. An
        # explicitly named managed identity is the sole Azure-specific override we
        # add; all other standard Azure Identity settings remain untouched.
        managed_identity_client_id = self._setting("MANAGED_IDENTITY_CLIENT_ID")
        credential_kwargs: dict[str, str] = {}
        if managed_identity_client_id:
            credential_kwargs["managed_identity_client_id"] = managed_identity_client_id
        return BlobServiceClient(
            account_url, credential=DefaultAzureCredential(**credential_kwargs)
        )

    @staticmethod
    def _imports() -> tuple[Any, Any, Any]:
        from azure.core.credentials import AzureSasCredential
        from azure.identity import DefaultAzureCredential  # type: ignore[import-untyped]
        from azure.storage.blob import BlobServiceClient

        return DefaultAzureCredential, BlobServiceClient, AzureSasCredential

    @staticmethod
    def _lease_import() -> Any:
        from azure.storage.blob import BlobLeaseClient

        return BlobLeaseClient

    def _account_url(self, account: str) -> str:
        endpoint = self._setting("ACCOUNT_URL")
        if endpoint:
            return endpoint.format(account=account).rstrip("/")
        suffix = self._setting("ENDPOINT_SUFFIX", default="blob.core.windows.net")
        return f"https://{account}.{suffix.strip('/')}"

    def _setting(self, name: str, *, default: str = "") -> str:
        value = self._environment.get(f"SCLPL_AZURE_BLOB_{name}")
        if value is not None:
            return value.strip()
        configured = self._configuration.get(name.lower())
        return configured.strip() if isinstance(configured, str) else default

    @staticmethod
    def _select_profile(configuration: Mapping[str, Any]) -> dict[str, Any]:
        selected = configuration.get("profile")
        profiles = configuration.get("profiles", {})
        base = {
            key: value for key, value in configuration.items() if key not in {"profile", "profiles"}
        }
        if selected is None:
            return base
        if not isinstance(selected, str) or not isinstance(profiles, Mapping):
            raise ResourceAuthenticationError("azure_blob profile configuration is invalid")
        profile = profiles.get(selected)
        if not isinstance(profile, Mapping):
            raise ResourceAuthenticationError(f"azure_blob profile {selected!r} is not configured")
        return {**base, **profile}

    def _secret(self, name: str, fallback: str | None = None) -> str:
        value = self._setting(name)
        if not value and fallback is not None:
            value = self._environment.get(fallback, "").strip()
        if not value:
            raise ResourceAuthenticationError(
                f"azblob authentication mode requires SCLPL_AZURE_BLOB_{name}"
            )
        return value

    def _transfer_options(self) -> dict[str, int]:
        """Azure SDK transfer settings, intentionally namespaced to this provider."""
        value = self._setting("MAX_CONCURRENCY")
        if not value:
            return {}
        try:
            concurrency = int(value)
        except ValueError as error:
            raise ResourceUnavailable(
                "SCLPL_AZURE_BLOB_MAX_CONCURRENCY must be an integer"
            ) from error
        if concurrency < 1:
            raise ResourceUnavailable("SCLPL_AZURE_BLOB_MAX_CONCURRENCY must be at least 1")
        return {"max_concurrency": concurrency}

    def _copy_source_url(self, uri: str) -> str:
        """Translate only for Azure's API; logical identities stay ``azblob://``."""
        details = parse_uri(uri)
        endpoint = urlsplit(self._account_url(details.account))
        path = "/".join(
            (endpoint.path.rstrip("/"), quote(details.container), quote(details.blob, safe="/"))
        )
        return urlunsplit((endpoint.scheme, endpoint.netloc, path, urlsplit(uri).query, ""))

    def _wait_for_copy(self, client: Any, uri: str) -> Any:
        deadline = time.monotonic() + self._copy_timeout()
        while True:
            properties = client.get_blob_properties()
            status = getattr(getattr(properties, "copy", None), "status", "success").lower()
            if status == "success":
                return properties
            if status != "pending":
                raise ResourceUnavailable(f"Azure Blob {self.display_uri(uri)}: copy {status}")
            if time.monotonic() >= deadline:
                raise ResourceUnavailable(f"Azure Blob {self.display_uri(uri)}: copy timed out")
            time.sleep(0.2)

    def _copy_timeout(self) -> float:
        value = self._setting("COPY_TIMEOUT", default="300")
        try:
            timeout = float(value)
        except ValueError as error:
            raise ResourceUnavailable("SCLPL_AZURE_BLOB_COPY_TIMEOUT must be a number") from error
        if timeout <= 0:
            raise ResourceUnavailable("SCLPL_AZURE_BLOB_COPY_TIMEOUT must be positive")
        return timeout

    def _blob(self, uri: str) -> Any:
        details = parse_uri(uri)
        if not details.blob:
            raise ResourceInvalidURI("azblob operation requires a blob, not only a container")
        query = parse_qs(urlsplit(uri).query)
        kwargs: dict[str, str] = {}
        if query.get("versionid"):
            kwargs["version_id"] = query["versionid"][0]
        if query.get("snapshot"):
            kwargs["snapshot"] = query["snapshot"][0]
        return self._service(details.account).get_blob_client(
            details.container, details.blob, **kwargs
        )

    def _info(self, uri: str, props: Any) -> ResourceInfo:
        return ResourceInfo(
            uri=self.normalize(uri),
            size=getattr(props, "size", None),
            modified=getattr(props, "last_modified", None),
            revision=getattr(props, "etag", None),
            content_type=getattr(getattr(props, "content_settings", None), "content_type", None),
            metadata=dict(getattr(props, "metadata", None) or {}),
        )

    def _translate(self, error: Exception, uri: str) -> SclplError:
        status = getattr(error, "status_code", None)
        message = f"Azure Blob {self.display_uri(uri)}: {self._redact_error(str(error))}"
        if status == 404:
            return ResourceNotFound(message)
        if status in (401,):
            return ResourceAuthenticationError(message)
        if status == 403:
            return ResourcePermissionDenied(message)
        if status in (409, 412):
            return ResourceConflict(message)
        return ResourceUnavailable(message)

    def _redact_error(self, text: str) -> str:
        """Configured credentials must not leak through Azure SDK diagnostics."""
        secrets = [
            self._setting("CONNECTION_STRING"),
            self._environment.get("AZURE_STORAGE_CONNECTION_STRING", ""),
            self._setting("ACCOUNT_KEY"),
            self._setting("SAS_TOKEN"),
        ]
        for secret in secrets:
            if secret:
                text = text.replace(secret, "[redacted]")
        return text
