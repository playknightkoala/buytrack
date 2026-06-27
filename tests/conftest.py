from __future__ import annotations

import pytest


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="執行標記為 network 的測試（會連外網）",
    )


def pytest_collection_modifyitems(config, items) -> None:
    if config.getoption("--run-network"):
        return
    skip_network = pytest.mark.skip(reason="需要 --run-network 才執行")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)
