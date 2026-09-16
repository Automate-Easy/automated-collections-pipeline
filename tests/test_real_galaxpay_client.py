"""
Tests the real Galax Pay HTTP client behavior.

External HTTP calls are mocked so authentication, filtering, pagination,
token refresh, and error handling can be tested without real credentials.
"""

import base64
from datetime import date
from unittest.mock import Mock, call, patch

import pytest
import requests

from src.clients.galaxpay.real_client import RealGalaxPayClient


def create_response(
    status_code: int,
    json_data: dict | list | None = None,
) -> Mock:
    response = Mock(spec=requests.Response)
    response.status_code = status_code

    if json_data is not None:
        response.json.return_value = json_data

    if 400 <= status_code:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"HTTP {status_code}"
        )
    else:
        response.raise_for_status.return_value = None

    return response


@patch("src.clients.galaxpay.real_client.requests.get")
@patch("src.clients.galaxpay.real_client.requests.post")
def test_authenticates_and_requests_expected_collection_window(
    mocked_post,
    mocked_get,
):
    mocked_post.return_value = create_response(
        200,
        {
            "access_token": "test-access-token",
        },
    )

    mocked_get.return_value = create_response(
        200,
        {
            "Transactions": [
                {
                    "galaxPayId": 1001,
                }
            ]
        },
    )

    client = RealGalaxPayClient(
        galax_id="test-galax-id",
        galax_hash="test-galax-hash",
    )

    transactions = client.get_pending_transactions(
        reference_date=date(2026, 9, 16)
    )

    assert transactions == [
        {
            "galaxPayId": 1001,
        }
    ]

    expected_credentials = base64.b64encode(
        b"test-galax-id:test-galax-hash"
    ).decode("utf-8")

    mocked_post.assert_called_once_with(
        "https://api.sandbox.cel.cash/v2/token",
        headers={
            "Authorization": f"Basic {expected_credentials}",
        },
        timeout=30,
    )

    mocked_get.assert_called_once_with(
        "https://api.sandbox.cel.cash/v2/transactions",
        headers={
            "Authorization": "Bearer test-access-token",
        },
        params={
            "payDayFrom": "2026-09-01",
            "payDayTo": "2026-09-21",
            "status": "pendingBoleto",
            "startAt": 0,
            "limit": 100,
        },
        timeout=30,
    )


@patch("src.clients.galaxpay.real_client.requests.get")
@patch("src.clients.galaxpay.real_client.requests.post")
def test_paginates_until_last_partial_page(
    mocked_post,
    mocked_get,
):
    mocked_post.return_value = create_response(
        200,
        {
            "access_token": "test-access-token",
        },
    )

    first_page = [
        {
            "galaxPayId": transaction_id,
        }
        for transaction_id in range(100)
    ]

    second_page = [
        {
            "galaxPayId": 100,
        },
        {
            "galaxPayId": 101,
        },
    ]

    mocked_get.side_effect = [
        create_response(
            200,
            {
                "Transactions": first_page,
            },
        ),
        create_response(
            200,
            {
                "Transactions": second_page,
            },
        ),
    ]

    client = RealGalaxPayClient(
        galax_id="test-galax-id",
        galax_hash="test-galax-hash",
    )

    transactions = client.get_pending_transactions(
        reference_date=date(2026, 9, 16)
    )

    assert len(transactions) == 102

    assert mocked_get.call_count == 2

    first_request = mocked_get.call_args_list[0]
    second_request = mocked_get.call_args_list[1]

    assert first_request.kwargs["params"]["startAt"] == 0
    assert second_request.kwargs["params"]["startAt"] == 100

    # The access token is reused across pages instead of authenticating
    # again for every request.
    assert mocked_post.call_count == 1


@patch("src.clients.galaxpay.real_client.requests.get")
@patch("src.clients.galaxpay.real_client.requests.post")
def test_returns_empty_list_when_no_transactions_are_found(
    mocked_post,
    mocked_get,
):
    mocked_post.return_value = create_response(
        200,
        {
            "access_token": "test-access-token",
        },
    )

    mocked_get.return_value = create_response(
        404,
        {},
    )

    client = RealGalaxPayClient(
        galax_id="test-galax-id",
        galax_hash="test-galax-hash",
    )

    transactions = client.get_pending_transactions(
        reference_date=date(2026, 9, 16)
    )

    assert transactions == []


@patch("src.clients.galaxpay.real_client.requests.get")
@patch("src.clients.galaxpay.real_client.requests.post")
def test_refreshes_token_once_after_unauthorized_response(
    mocked_post,
    mocked_get,
):
    mocked_post.side_effect = [
        create_response(
            200,
            {
                "access_token": "expired-token",
            },
        ),
        create_response(
            200,
            {
                "access_token": "refreshed-token",
            },
        ),
    ]

    mocked_get.side_effect = [
        create_response(
            401,
            {},
        ),
        create_response(
            200,
            {
                "Transactions": [
                    {
                        "galaxPayId": 1001,
                    }
                ]
            },
        ),
    ]

    client = RealGalaxPayClient(
        galax_id="test-galax-id",
        galax_hash="test-galax-hash",
    )

    transactions = client.get_pending_transactions(
        reference_date=date(2026, 9, 16)
    )

    assert transactions == [
        {
            "galaxPayId": 1001,
        }
    ]

    assert mocked_post.call_count == 2

    assert mocked_get.call_args_list[0].kwargs["headers"] == {
        "Authorization": "Bearer expired-token",
    }

    assert mocked_get.call_args_list[1].kwargs["headers"] == {
        "Authorization": "Bearer refreshed-token",
    }


@patch("src.clients.galaxpay.real_client.requests.get")
@patch("src.clients.galaxpay.real_client.requests.post")
def test_raises_http_error_for_transaction_request_failure(
    mocked_post,
    mocked_get,
):
    mocked_post.return_value = create_response(
        200,
        {
            "access_token": "test-access-token",
        },
    )

    mocked_get.return_value = create_response(
        403,
        {},
    )

    client = RealGalaxPayClient(
        galax_id="test-galax-id",
        galax_hash="test-galax-hash",
    )

    with pytest.raises(requests.HTTPError):
        client.get_pending_transactions(
            reference_date=date(2026, 9, 16)
        )


@patch("src.clients.galaxpay.real_client.requests.post")
def test_raises_error_when_authentication_response_has_no_access_token(
    mocked_post,
):
    mocked_post.return_value = create_response(
        200,
        {
            "expires_in": 600,
        },
    )

    client = RealGalaxPayClient(
        galax_id="test-galax-id",
        galax_hash="test-galax-hash",
    )

    with pytest.raises(
        RuntimeError,
        match="did not contain an access_token",
    ):
        client.get_pending_transactions(
            reference_date=date(2026, 9, 16)
        )


@patch("src.clients.galaxpay.real_client.requests.get")
@patch("src.clients.galaxpay.real_client.requests.post")
def test_raises_error_for_unexpected_transactions_response(
    mocked_post,
    mocked_get,
):
    mocked_post.return_value = create_response(
        200,
        {
            "access_token": "test-access-token",
        },
    )

    mocked_get.return_value = create_response(
        200,
        {
            "unexpectedField": [],
        },
    )

    client = RealGalaxPayClient(
        galax_id="test-galax-id",
        galax_hash="test-galax-hash",
    )

    with pytest.raises(
        RuntimeError,
        match="Unexpected Galax Pay transactions response format",
    ):
        client.get_pending_transactions(
            reference_date=date(2026, 9, 16)
        )