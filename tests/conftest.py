import pytest


def pytest_configure(config: pytest.Config) -> None:
    # Installed package: the pytest11 entry point already loaded the plugin as "morpheus_vlt".
    # Bare checkout: nobody did, so load it here. Loading it twice makes pluggy very upset.
    if not config.pluginmanager.has_plugin("morpheus_vlt"):
        config.pluginmanager.import_plugin("morpheus_vlt.pytest_plugin")
