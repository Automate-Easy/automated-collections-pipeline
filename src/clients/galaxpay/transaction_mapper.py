"""
Maps Galax Pay transaction responses to collection domain models.

This module isolates the external Galax Pay API schema from the application's
internal domain representation.
"""

from datetime import datetime

from src.models.collectible_debt import CollectibleDebt


class GalaxPayTransactionMapper:

    @staticmethod
    def to_collectible_debt(transaction: dict) -> CollectibleDebt:
        # Customer information is nested inside the transaction's charge.
        # Extracting it here prevents the rest of the application from depending
        # on the Galax Pay response structure.
        customer = transaction["Charge"][0]["Customer"]

        return CollectibleDebt(
            galaxpay_transaction_id=transaction["galaxPayId"],
            customer_id=customer["galaxPayId"],
            customer_name=customer["name"],

            # Galax Pay returns phone numbers as numeric values, but phone numbers
            # are identifiers rather than quantities, so we normalize them to strings.
            customer_phones=[
                str(phone)
                for phone in customer["phones"]
            ],

            # Monetary values are kept in integer cents throughout the pipeline
            # to avoid floating-point precision issues.
            amount_cents=transaction["value"],

            due_date=datetime.strptime(
                transaction["payday"],
                "%Y-%m-%d",
            ).date(),

            # The bank line belongs to the boleto associated with this transaction
            # and must remain linked to the debt throughout the collection pipeline.
            bank_line=transaction["Boleto"]["bankLine"],
        )