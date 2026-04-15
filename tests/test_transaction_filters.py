from typing import Any

import pytest

from src.common.transaction_filters import (
    is_deleted_expense,
    is_deleted_transaction,
    is_excluded_description,
    is_payment_transaction,
    is_refund_transaction,
)


class MockExpense:
    def __init__(self, deleted_at=None):
        self.deleted_at = deleted_at


class MockTransaction:
    def __init__(
        self, splitwise_deleted_at=None, is_refund=False, description=None, merchant=None
    ):
        self.splitwise_deleted_at = splitwise_deleted_at
        self.is_refund = is_refund
        self.description = description
        self.merchant = merchant


def test_is_deleted_expense():
    assert is_deleted_expense(MockExpense(deleted_at="2023-01-01T00:00:00Z")) is True
    assert is_deleted_expense(MockExpense(deleted_at="")) is False
    assert is_deleted_expense(MockExpense(deleted_at=None)) is False

    # Object without deleted_at attribute
    class NoDeletedAtObj:
        pass

    assert is_deleted_expense(NoDeletedAtObj()) is False


def test_is_deleted_transaction():
    assert is_deleted_transaction(MockTransaction(splitwise_deleted_at="2023-01-01")) is True
    assert is_deleted_transaction(MockTransaction(splitwise_deleted_at="")) is False
    assert is_deleted_transaction(MockTransaction(splitwise_deleted_at=None)) is False


def test_is_payment_transaction():
    # Exact matches
    assert is_payment_transaction("Settle all balances") is True
    assert is_payment_transaction("payment") is True

    # Substring matches
    assert is_payment_transaction("Autopay - Thank you") is True
    assert is_payment_transaction("MOBILE PAYMENT") is True
    assert is_payment_transaction("Please settle this soon") is True

    # Non-matches
    assert is_payment_transaction("Target Purchase") is False
    assert is_payment_transaction("") is False
    assert is_payment_transaction("Refund from Amazon") is False


def test_is_refund_transaction():
    # Case 1: Explicit is_refund flag
    assert is_refund_transaction(MockTransaction(is_refund=True)) is True
    
    # Case 2: Flag is False, but description has refund keyword
    assert is_refund_transaction(MockTransaction(is_refund=False, description="Amazon Refund")) is True
    assert is_refund_transaction(MockTransaction(is_refund=False, description="Target Return")) is True
    assert is_refund_transaction(MockTransaction(is_refund=False, description="Store Credit")) is True
    
    # Case 3: Flag is False, merchant has refund keyword
    assert is_refund_transaction(MockTransaction(is_refund=False, merchant="Refund Department")) is True

    # Case 4: Not a refund
    assert is_refund_transaction(MockTransaction(is_refund=False, description="Target Purchase")) is False
    assert is_refund_transaction(MockTransaction(is_refund=False)) is False

    # Case 5: check_description=False
    assert is_refund_transaction(MockTransaction(is_refund=False, description="Amazon Refund"), check_description=False) is False


def test_is_excluded_description():
    # Should mirror is_payment_transaction for now
    assert is_excluded_description("Settle all balances") is True
    assert is_excluded_description("Grocery Shopping") is False
