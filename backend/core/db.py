"""Reading many rows with encrypted columns quickly, on Django's own connection and transaction."""

import psycopg
from django.db import connection


def fetch_binary(sql: str, params: list) -> list[tuple]:
    """Rows with bytea in binary form.

    Django's cursor binds parameters client-side, and psycopg can then only return text, where
    bytea arrives hex-encoded: twice the bytes from the database and decoding work on a small
    CPU. The query is still fully parameterised. Being a plain psycopg cursor, it bypasses
    Django's query hooks (the DEBUG query log, execute_wrapper).
    """
    connection.ensure_connection()
    with psycopg.Cursor(connection.connection) as cursor:
        cursor.execute(sql, params, binary=True)
        return cursor.fetchall()


def uuid_array(raw_ids) -> str:
    """Ids given as their 16 bytes, as one `uuid[]` literal for `= ANY(%s::uuid[])`.

    One text parameter that Postgres parses, instead of thousands of UUID objects that the
    driver adapts one by one: for 8,000 ids, about a tenth of the CPU. Only hex digits and commas
    go into it, so it can't carry anything but ids."""
    return "{" + ",".join(bytes(raw).hex() for raw in raw_ids) + "}"
