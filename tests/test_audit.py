"""Журнал решений: запись, фильтры и ротация"""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from utils.access.audit import AuditLog, PostgresAudit
from utils.storage import db_connect


class AuditLogTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'audit.jsonl'
        self.audit = AuditLog(self.path, max_bytes=1000)

    def test_append_and_read_newest_first(self):
        for index in range(3):
            self.audit.append({
                'decision': 'GRANTED' if index % 2 == 0 else 'DENIED',
                'session_id': str(index),
            })
        items = self.audit.read(limit=10)
        self.assertEqual([item['session_id'] for item in items], ['2', '1', '0'])
        self.assertEqual(len(self.audit.read(limit=1)), 1)

    def test_decision_filter(self):
        self.audit.append({'decision': 'GRANTED', 'session_id': 'a'})
        self.audit.append({'decision': 'DENIED', 'session_id': 'b'})
        self.assertEqual(
            [item['session_id'] for item in self.audit.read(decision='DENIED')],
            ['b'],
        )

    def test_kind_filter_and_broken_lines(self):
        self.audit.append({'type': 'session', 'decision': 'GRANTED', 'session_id': 'a'})
        self.audit.append({'type': 'policy', 'values': {}})
        with self.path.open('a', encoding='utf-8') as file:
            file.write('not json\n')
        self.assertEqual(len(self.audit.read(kind='session')), 1)
        self.assertEqual(len(self.audit.read()), 2)

    def test_rotation_keeps_one_backup(self):
        self.audit = AuditLog(self.path, max_bytes=1)
        self.audit.append({'session_id': 'first'})
        self.audit.append({'session_id': 'second'})
        self.assertTrue(Path(str(self.path) + '.1').is_file())
        self.assertEqual(self.audit.read()[0]['session_id'], 'second')


if __name__ == '__main__':
    unittest.main()


class PostgresAuditTests(unittest.TestCase):
    def test_append_is_queued_and_flushed(self):
        with patch('utils.access.audit.add_audit_record') as add:
            audit = PostgresAudit()
            audit.append({'type': 'session', 'session_id': 'a'})
            self.assertTrue(audit.flush(1.0))
        add.assert_called_once_with({'type': 'session', 'session_id': 'a'})

    def test_write_failure_does_not_raise(self):
        with patch('utils.access.audit.add_audit_record',
                   side_effect=RuntimeError('db')):
            audit = PostgresAudit()
            audit.append({'type': 'session'})
            self.assertTrue(audit.flush(1.0))

    def test_read_delegates_to_database(self):
        with patch('utils.access.audit.get_audit_records',
                   return_value=[{'session_id': 'a'}]) as read:
            records = PostgresAudit().read(
                limit=10, decision='DENIED', kind='session',
            )
        self.assertEqual(records, [{'session_id': 'a'}])
        read.assert_called_once_with(
            limit=10, decision='DENIED', kind='session',
        )

    def test_read_failure_is_propagated(self):
        with patch('utils.access.audit.get_audit_records',
                   side_effect=RuntimeError('db')):
            with self.assertRaises(RuntimeError):
                PostgresAudit().read()


class FakeCursor:
    def __init__(self):
        self.statements = []
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        pass


class AuditSqlTests(unittest.TestCase):
    def test_add_record_passes_all_fields(self):
        connection = FakeConnection()
        with patch.object(db_connect, 'create_connection', return_value=connection):
            db_connect.add_audit_record({
                'timestamp': '2026-01-01T00:00:00+00:00',
                'type': 'session', 'session_id': 's1', 'decision': 'DENIED',
                'reason': 'x', 'user_id': 7, 'distance': 0.1,
                'checks': {'recognition': {}}, 'stereo_decision': 'SPOOF',
                'stereo_reason': 'flat', 'duration_seconds': 1.5,
                'unlock_attempted': False,
            })
        sql, params = connection.cursor_obj.statements[0]
        self.assertIn('INSERT INTO access_audit', sql)
        self.assertEqual(len(params), 13)
        self.assertEqual(params[2], 's1')
        self.assertEqual(params[3], 'DENIED')

    def test_get_records_builds_filters_and_maps_rows(self):
        connection = FakeConnection()
        connection.cursor_obj.rows = [(
            datetime(2026, 1, 1, tzinfo=timezone.utc), 'session', 's1',
            'GRANTED', '', 7, 0.1, {'recognition': {'status': 'PASS'}},
            None, None, 1.0, True, None,
        )]
        with patch.object(db_connect, 'create_connection', return_value=connection):
            records = db_connect.get_audit_records(
                limit=10, decision='DENIED', kind='session',
            )
        self.assertEqual(records[0]['timestamp'], '2026-01-01T00:00:00+00:00')
        self.assertEqual(records[0]['decision'], 'GRANTED')
        self.assertEqual(records[0]['checks']['recognition']['status'], 'PASS')
        sql, params = connection.cursor_obj.statements[0]
        self.assertIn('WHERE type = %s AND decision = %s', sql)
        self.assertEqual(params, ('session', 'DENIED', 10))

    def test_audit_table_is_created_with_others(self):
        with patch.object(db_connect, 'initialize_pgvector'), \
                patch.object(db_connect, 'create_embeddings_table'), \
                patch.object(db_connect, 'create_users_table'), \
                patch.object(db_connect, 'create_users_to_embeddings_table'), \
                patch.object(db_connect, 'create_access_audit_table') as audit:
            db_connect.create_embeddings_tables()
        audit.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
