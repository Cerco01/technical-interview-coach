from __future__ import annotations

from typing import Any


PYTHON_SPECS: dict[str, dict[str, Any]] = {
    "q-python-003": {
        "entrypoint": "count_words",
        "cases": [
            {"name": "normalizes and ignores empty", "args": [["Python", "python", "", "SQL"]], "expected": {"python": 2, "sql": 1}},
            {"name": "empty input", "args": [[]], "expected": {}},
        ],
    },
    "q-python-005": {
        "entrypoint": "top_event_types",
        "cases": [
            {"name": "frequency and tie ordering", "args": [["view", "buy", "view", "cart", "buy", "cart"], 2], "expected": ["buy", "cart"]},
            {"name": "zero and oversized k", "args": [["b", "a", "b"], 0], "expected": []},
            {"name": "oversized k", "args": [["b", "a", "b"], 9], "expected": ["b", "a"]},
        ],
    },
    "q-python-006": {
        "entrypoint": "merge_intervals",
        "cases": [
            {"name": "nested and touching intervals", "args": [[[5, 7], [1, 3], [3, 6], [2, 2], [10, 11]]], "expected": [[1, 7], [10, 11]], "preserve_arg": 0},
            {"name": "empty input", "args": [[]], "expected": []},
        ],
    },
    "q-python-007": {
        "entrypoint": "unique_in_order",
        "materialize": True,
        "cases": [
            {"name": "stable first occurrences", "args": [[3, 1, 3, 2, 1]], "expected": [3, 1, 2]},
            {"name": "one-pass iterable", "args": [{"__iterator__": ["a", "a", "b"]}], "expected": ["a", "b"]},
        ],
    },
    "q-python-008": {
        "entrypoint": "chunks",
        "materialize": True,
        "cases": [
            {"name": "full and partial chunks", "args": [{"__iterator__": [1, 2, 3, 4, 5]}, 2], "expected": [[1, 2], [3, 4], [5]]},
            {"name": "empty input", "args": [[], 3], "expected": []},
            {"name": "rejects non-positive size", "args": [[], 0], "raises": "ValueError"},
        ],
    },
    "q-numpy-001": {
        "entrypoint": "center_columns",
        "numpy": True,
        "cases": [
            {"name": "centers each feature", "args": [{"__ndarray__": [[1.0, 10.0], [3.0, 14.0], [5.0, 18.0]]}], "expected_array": [[-2.0, -4.0], [0.0, 0.0], [2.0, 4.0]], "preserve_arg": 0},
            {"name": "single row", "args": [{"__ndarray__": [[2.0, -1.0]]}], "expected_array": [[0.0, 0.0]]},
        ],
    },
    "q-numpy-002": {
        "entrypoint": "normalize_rows",
        "numpy": True,
        "cases": [
            {"name": "normalizes and preserves zero rows", "args": [{"__ndarray__": [[3.0, 4.0], [0.0, 0.0], [-5.0, 0.0]]}], "expected_array": [[0.6, 0.8], [0.0, 0.0], [-1.0, 0.0]], "preserve_arg": 0, "finite": True},
        ],
    },
    "q-numpy-004": {
        "entrypoint": "masked_column_means",
        "numpy": True,
        "cases": [
            {"name": "valid and empty columns", "args": [{"__ndarray__": [[1.0, 9.0, 2.0], [3.0, 8.0, 6.0]]}, {"__ndarray__": [[True, False, True], [True, False, False]], "dtype": "bool"}], "expected_array": [2.0, float("nan"), 2.0]},
        ],
    },
    "q-stats-006": {"entrypoint": "simulate_first_success", "numpy": True, "custom": "first_success"},
    "q-stats-007": {"entrypoint": "bootstrap_median_difference", "numpy": True, "custom": "bootstrap"},
    "q-pandas-002": {
        "entrypoint": "filter_adults",
        "pandas": True,
        "cases": [{"name": "filters threshold, country, and missing ages", "args": [{"__dataframe__": {"id": [1, 2, 3, 4, 5], "age": [18.0, 17.0, None, 40.0, 25.0], "country": ["US", "US", "CA", "MX", "CA"]}}], "expected_records": [{"id": 1, "age": 18.0, "country": "US"}, {"id": 5, "age": 25.0, "country": "CA"}]}],
    },
    "q-pandas-003": {
        "entrypoint": "grouped_revenue",
        "pandas": True,
        "cases": [{"name": "aggregates and sorts revenue", "args": [{"__dataframe__": {"region": ["east", "west", "east"], "quantity": [2, 1, 3], "unit_price": [10.0, 50.0, 5.0]}}], "expected_records": [{"region": "west", "total_revenue": 50.0, "order_count": 1}, {"region": "east", "total_revenue": 35.0, "order_count": 2}]}],
    },
    "q-pandas-005": {"entrypoint": "clean_accounts", "pandas": True, "custom": "clean_accounts"},
    "q-pandas-007": {"entrypoint": "normalize_timestamps", "pandas": True, "custom": "timestamps"},
    "q-pandas-008": {"entrypoint": "reshape_metrics", "pandas": True, "custom": "reshape"},
}


SQL_SPECS: dict[str, dict[str, Any]] = {
    "q-sql-001": {
        "setup": ["CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT NOT NULL)", "CREATE TABLE orders(id INTEGER PRIMARY KEY, customer_id INTEGER, created_at TEXT)", "INSERT INTO customers VALUES (1,'Ada'),(2,'Linus'),(3,'Grace')", "INSERT INTO orders VALUES (10,1,'2026-01-01'),(11,1,'2026-01-02'),(12,3,'2026-01-03')"],
        "columns": ["id", "name"], "rows": [[2, "Linus"]], "order_sensitive": False,
    },
    "q-sql-002": {
        "setup": ["CREATE TABLE orders(id INTEGER PRIMARY KEY, customer_id INTEGER, status TEXT)", "CREATE TABLE order_items(order_id INTEGER, quantity INTEGER, unit_price REAL)", "INSERT INTO orders VALUES (1,10,'completed'),(2,10,'cancelled'),(3,20,'completed'),(4,30,'completed')", "INSERT INTO order_items VALUES (1,2,600),(2,10,900),(3,1,1000),(4,3,400)"],
        "columns": ["customer_id", "revenue"], "rows": [[10, 1200.0], [30, 1200.0]], "order_sensitive": False,
    },
    "q-sql-003": {
        "setup": ["CREATE TABLE employees(id INTEGER PRIMARY KEY, salary INTEGER)", "INSERT INTO employees VALUES (1,100),(2,100),(3,80),(4,70)"],
        "columns": ["salary"], "rows": [[80]], "order_sensitive": False,
    },
    "q-sql-004": {
        "setup": ["CREATE TABLE events(id INTEGER PRIMARY KEY, user_id INTEGER, event_type TEXT, occurred_at TEXT)", "INSERT INTO events VALUES (1,10,'open','2026-01-01'),(2,10,'buy','2026-01-02'),(3,10,'close','2026-01-02'),(4,20,'open','2026-01-03')"],
        "columns": ["id", "user_id", "event_type", "occurred_at"], "rows": [[3,10,"close","2026-01-02"],[4,20,"open","2026-01-03"]], "order_sensitive": False,
    },
    "q-sql-005": {
        "setup": ["CREATE TABLE payments(customer_id INTEGER, amount REAL, status TEXT)", "INSERT INTO payments VALUES (1,10,'successful'),(1,NULL,'successful'),(1,50,'failed'),(2,NULL,'failed'),(3,NULL,'successful')"],
        "columns": ["customer_id", "successful_rows", "known_successful_amounts", "successful_total"], "rows": [[1,2,1,10.0],[2,0,0,0],[3,1,0,0]], "order_sensitive": False,
    },
    "q-sql-006": {
        "setup": ["CREATE TABLE contact_imports(row_id INTEGER PRIMARY KEY, email TEXT, imported_at TEXT, payload TEXT)", "INSERT INTO contact_imports VALUES (1,'a@example.test','2026-01-01','old'),(2,'a@example.test','2026-01-02','new'),(3,'a@example.test','2026-01-02','winner'),(4,'b@example.test','2026-01-03','only'),(5,NULL,'2026-01-04','excluded')"],
        "columns": ["row_id", "email", "imported_at", "payload"], "rows": [[3,"a@example.test","2026-01-02","winner"],[4,"b@example.test","2026-01-03","only"]], "order_sensitive": False,
    },
    "q-sql-007": {
        "setup": ["CREATE TABLE daily_orders(order_date TEXT PRIMARY KEY, order_count INTEGER)", "INSERT INTO daily_orders VALUES ('2026-01-01',1),('2026-01-02',2),('2026-01-03',3),('2026-01-04',4),('2026-01-05',5),('2026-01-06',6),('2026-01-07',7),('2026-01-08',8)"],
        "columns": ["order_date", "rolling_total"], "rows": [["2026-01-01",1],["2026-01-02",3],["2026-01-03",6],["2026-01-04",10],["2026-01-05",15],["2026-01-06",21],["2026-01-07",28],["2026-01-08",35]], "order_sensitive": True,
    },
}
