"""Connector sync entry point — `make sync` or `python -m truthguard.connectors.sync`."""
from __future__ import annotations

from truthguard import config


def main() -> None:
    if not config.ENABLE_CONNECTORS:
        print("ENABLE_CONNECTORS=false — connectors are disabled.")
        return
    # TODO(phase1): implement FolderConnector, SharePoint, email
    print("Connectors not yet implemented. Set ENABLE_CONNECTORS=true when ready.")


if __name__ == "__main__":
    main()
