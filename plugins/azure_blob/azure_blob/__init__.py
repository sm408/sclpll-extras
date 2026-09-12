"""Local development form of the ``sclpl-azure-blob`` resource plugin."""

from sclpl.ext.api import plugin_settings, register_resource_provider

from .provider import AzureBlobProvider


def register() -> None:
    register_resource_provider(
        "azblob", AzureBlobProvider(configuration=plugin_settings("azure_blob"))
    )
