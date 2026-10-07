from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class PluginDescriptor:
    """Static facts about a plugin, loaded even when the plugin is disabled.

    Holds data only, no analysis code. `extensions` maps each file extension
    the plugin claims to the language label those files get.
    """

    name: str
    version: str
    api_version: int
    extensions: Mapping[str, str]
