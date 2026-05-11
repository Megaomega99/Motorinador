"""Fixtures shared across all tests."""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture(autouse=True)
def mock_serial_link():
    """Prevent tests from trying to open a real serial port."""
    with patch("app.serial_link.serial_asyncio.open_serial_connection") as m:
        reader = AsyncMock()
        reader.readline = AsyncMock(side_effect=asyncio.CancelledError)
        writer = AsyncMock()
        m.return_value = (reader, writer)
        yield m
