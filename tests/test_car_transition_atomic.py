import threading
import unittest

from tests.test_database_atomic_creation import database


class Cursor:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class CarState:
    def __init__(self):
        self.lock = threading.Lock()
        self.events = []
        self.next_id = 1

    def active_driver(self, family_id):
        active = {}
        names = {}
        for event in self.events:
            if event[4] != family_id:
                continue
            _, user_id, driver_name, status, _ = event
            key = ("user", user_id) if user_id is not None else ("name", driver_name)
            if status == "connected":
                active[key] = True
                names[key] = (driver_name, user_id)
            else:
                active.pop(key, None)
                names.pop(key, None)
        remaining = [names[key] for key in active]
        return remaining[-1] if remaining else None


class Transaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.connection.locked:
            self.connection.state.lock.release()
            self.connection.locked = False
        return False


class Connection:
    def __init__(self, state):
        self.state = state
        self.locked = False

    def transaction(self):
        return Transaction(self)

    def execute(self, sql, parameters):
        if "pg_advisory_xact_lock" in sql:
            self.state.lock.acquire()
            self.locked = True
            return Cursor((True,))
        if "FROM car_events c" in sql:
            return Cursor(self.state.active_driver(parameters[0]))
        if "INSERT INTO car_events" in sql:
            user_id, driver_name, status, _event_time, family_id = parameters
            event_id = self.state.next_id
            self.state.next_id += 1
            self.state.events.append((event_id, user_id, driver_name, status, family_id))
            return Cursor((event_id,))
        raise AssertionError(sql)


class ConnectionContext:
    def __init__(self, state):
        self.connection = Connection(state)

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class Pool:
    def __init__(self, state):
        self.state = state

    def connection(self):
        return ConnectionContext(self.state)


class AtomicCarTransitionTests(unittest.TestCase):
    def setUp(self):
        self.state = CarState()
        self.original_pool = database.pool
        database.pool = Pool(self.state)

    def tearDown(self):
        database.pool = self.original_pool

    def test_duplicate_sequential_connect_is_noop(self):
        first = database.connect_car_atomically(1, "A1", 10)
        second = database.connect_car_atomically(1, "A1", 10)
        self.assertEqual(first["transition"], "connected")
        self.assertEqual(second, {
            "transition": "none", "reason": "already_active", "current_driver": "A1",
        })
        self.assertEqual([event[3] for event in self.state.events], ["connected"])

    def test_concurrent_duplicate_connect_creates_one_logical_transition(self):
        results = []
        threads = [
            threading.Thread(
                target=lambda: results.append(database.connect_car_atomically(1, "A1", 10))
            )
            for _ in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(result["transition"] == "connected" for result in results), 1)
        self.assertEqual(sum(result["transition"] == "none" for result in results), 1)
        self.assertEqual(len(self.state.events), 1)

    def test_handover_records_history_but_returns_only_final_connect_transition(self):
        database.connect_car_atomically(1, "A1", 10)
        result = database.connect_car_atomically(2, "A2", 10)
        self.assertEqual(result["transition"], "connected")
        self.assertEqual(result["event_id"], 3)
        self.assertEqual(
            [(event[1], event[3]) for event in self.state.events],
            [(1, "connected"), (1, "disconnected"), (2, "connected")],
        )

    def test_valid_disconnect_then_duplicate_disconnect(self):
        database.connect_car_atomically(1, "A1", 10)
        first = database.disconnect_car_atomically(1, 10)
        second = database.disconnect_car_atomically(1, 10)
        self.assertEqual(first["transition"], "disconnected")
        self.assertEqual(second, {"transition": "none", "reason": "already_available"})
        self.assertEqual([event[3] for event in self.state.events], ["connected", "disconnected"])

    def test_other_user_cannot_disconnect_active_driver(self):
        database.connect_car_atomically(1, "A1", 10)
        result = database.disconnect_car_atomically(2, 10)
        self.assertEqual(result, {
            "transition": "none", "reason": "different_driver", "current_driver": "A1",
        })
        self.assertEqual(len(self.state.events), 1)

    def test_family_locks_are_scoped_independently(self):
        database.connect_car_atomically(1, "A1", 10)
        database.connect_car_atomically(3, "B1", 20)
        self.assertEqual(self.state.active_driver(10), ("A1", 1))
        self.assertEqual(self.state.active_driver(20), ("B1", 3))


if __name__ == "__main__":
    unittest.main()
