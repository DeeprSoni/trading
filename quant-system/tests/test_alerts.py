"""Tests for Telegram alert system."""

from unittest.mock import patch, MagicMock
from src.alerts import TelegramAlerter


def test_not_configured_without_env():
    alerter = TelegramAlerter(token="", chat_id="")
    assert not alerter.is_configured
    assert alerter.send_immediate("test") is False


def test_configured_with_values():
    alerter = TelegramAlerter(token="fake_token", chat_id="12345")
    assert alerter.is_configured


@patch("src.alerts.requests.post")
def test_send_immediate(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    alerter = TelegramAlerter(token="token", chat_id="123")
    result = alerter.send_immediate("Stop loss hit on IC_001")
    assert result is True
    mock_post.assert_called_once()
    call_json = mock_post.call_args[1]["json"]
    assert "IMMEDIATE" in call_json["text"]
    assert "Stop loss" in call_json["text"]


@patch("src.alerts.requests.post")
def test_send_today(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    alerter = TelegramAlerter(token="token", chat_id="123")
    result = alerter.send_today("IC entry signal: IVR=45, VIX=18")
    assert result is True
    call_json = mock_post.call_args[1]["json"]
    assert "TODAY" in call_json["text"]


@patch("src.alerts.requests.post")
def test_send_monitor(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    alerter = TelegramAlerter(token="token", chat_id="123")
    result = alerter.send_monitor("IC_003 at 48% profit, watch tomorrow")
    assert result is True
    call_json = mock_post.call_args[1]["json"]
    assert "MONITOR" in call_json["text"]


@patch("src.alerts.requests.post")
def test_send_failure(mock_post):
    mock_post.return_value = MagicMock(status_code=400, text="Bad Request")
    alerter = TelegramAlerter(token="token", chat_id="123")
    result = alerter.send_raw("test")
    assert result is False
