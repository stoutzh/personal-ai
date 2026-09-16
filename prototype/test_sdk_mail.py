"""Offline tests for sdk_mail using synthetic JSON and fake subprocesses. No real mail, no network."""
import json
import os
import unittest

import sdk_mail
from sdk_mail import (
    MailError, list_unread, validate_account, validate_limit, build_command,
    parse_envelopes, format_item, collect_limited,
    ALLOWED_ACCOUNTS, MIN_LIMIT, MAX_LIMIT, HIMALAYA_BIN, MAX_OUTPUT_BYTES,
)


def make_proc(stdout=b'', stderr=b'', returncode=0, keep_stdout_open=False):
    r_out, w_out = os.pipe()
    r_err, w_err = os.pipe()
    if not keep_stdout_open:
        os.write(w_out, stdout)
        os.close(w_out)
    os.write(w_err, stderr)
    os.close(w_err)

    class Proc:
        def __init__(self):
            self.stdout = os.fdopen(r_out, 'rb', buffering=0)
            self.stderr = os.fdopen(r_err, 'rb', buffering=0)
            self.returncode = None
            self._w_out = w_out

        def wait(self, timeout=None):
            self.returncode = returncode
            return returncode

        def kill(self):
            try:
                os.close(self._w_out)
            except OSError:
                pass
            self.wait()

        def close(self):
            for stream in (self.stdout, self.stderr):
                try:
                    stream.close()
                except OSError:
                    pass

    return Proc()


def fake_runner(stdout_bytes=b''):
    def _run(cmd, timeout, max_bytes):
        return stdout_bytes
    return _run


class AccountValidationTests(unittest.TestCase):
    def test_allowed_accounts_pass(self):
        for account in ('gmail', 'ucsb', '163'):
            self.assertIsNone(validate_account(account))

    def test_unknown_and_malformed_accounts_rejected(self):
        for bad in (None, 123, '', 'GMAIL', ' gmail', 'gmail ', 'gmail; rm -rf /', '../gmail', 'gmail/../163'):
            with self.subTest(bad=bad), self.assertRaises(MailError):
                validate_account(bad)

    def test_account_is_whitelist_not_substring(self):
        with self.assertRaises(MailError):
            validate_account('not-gmail')


class LimitValidationTests(unittest.TestCase):
    def test_bounds_pass(self):
        for limit in (MIN_LIMIT, MAX_LIMIT, 5):
            self.assertIsNone(validate_limit(limit))

    def test_out_of_bounds_rejected(self):
        for bad in (0, -1, MAX_LIMIT + 1, 999):
            with self.subTest(bad=bad), self.assertRaises(MailError):
                validate_limit(bad)

    def test_non_int_and_bool_rejected(self):
        for bad in ('5', 5.0, True, False, None, [5], {'n': 5}):
            with self.subTest(bad=bad), self.assertRaises(MailError):
                validate_limit(bad)


class BuildCommandTests(unittest.TestCase):
    def test_fixed_argv_no_shell(self):
        cmd = build_command('gmail', 7)
        self.assertEqual(cmd, [
            HIMALAYA_BIN, 'envelope', 'search',
            '-a', 'gmail', '--json', '-s', '7', 'not flag seen order by date desc',
        ])
        # query is a single argv element (spaces preserved), never shell-split
        self.assertEqual(cmd[-1], 'not flag seen order by date desc')
        self.assertEqual(cmd[0], '/usr/local/bin/himalaya')


class ParseEnvelopesTests(unittest.TestCase):
    def test_normal(self):
        raw = json.dumps({'envelopes': [{'id': 1, 'subject': 'Hi'}]}).encode()
        self.assertEqual(parse_envelopes(raw), [{'id': 1, 'subject': 'Hi'}])

    def test_empty_list(self):
        self.assertEqual(parse_envelopes(b'{"envelopes":[]}'), [])

    def test_error_field_rejected_without_leaking_raw(self):
        with self.assertRaises(MailError):
            parse_envelopes(json.dumps({'error': 'IMAP SELECT failed: ...', 'backtrace': 'secret'}).encode())

    def test_invalid_json_rejected(self):
        for raw in (b'not json', b'', b'{broken', b'null', b'"envelopes"'):
            with self.subTest(raw=raw), self.assertRaises(MailError):
                parse_envelopes(raw)

    def test_missing_envelopes_rejected(self):
        for payload in ({'foo': 1}, {'envelopes': 'not-a-list'}, {'envelopes': None}):
            with self.subTest(payload=payload), self.assertRaises(MailError):
                parse_envelopes(json.dumps(payload).encode())


class FormatItemTests(unittest.TestCase):
    def test_full_fields(self):
        env = {'id': 42, 'from': [{'name': 'Alice', 'email': 'a@x.com'}], 'subject': 'Hi', 'date': '2026-09-10T00:00:00Z'}
        self.assertEqual(format_item('gmail', env), {
            'id': 42, 'sender': 'Alice', 'subject': 'Hi', 'date': '2026-09-10T00:00:00Z',
        })

    def test_chinese_fields_preserved(self):
        env = {'id': '1504911952', 'from': [{'name': '网易邮箱安全管家', 'email': 'member@service.netease.com'}],
               'subject': '登录安全，也能按你的习惯来', 'date': '2026-09-10T17:32:46+08:00'}
        item = format_item('163', env)
        self.assertEqual(item['sender'], '网易邮箱安全管家')
        self.assertEqual(item['subject'], '登录安全，也能按你的习惯来')

    def test_sender_falls_back_to_email(self):
        env = {'from': [{'name': None, 'email': 'sb.cashier@bfs.ucsb.edu'}]}
        self.assertEqual(format_item('ucsb', env)['sender'], 'sb.cashier@bfs.ucsb.edu')

    def test_missing_fields_defaulted(self):
        self.assertEqual(format_item('gmail', {}), {'id': None, 'sender': '', 'subject': '', 'date': ''})

    def test_non_dict_returns_none(self):
        for bad in ('str', 5, None, ['x']):
            self.assertIsNone(format_item('gmail', bad))

    def test_malformed_from_ignored(self):
        for frm in ('str', [5], [None], [{'nope': 1}]):
            env = {'from': frm}
            self.assertEqual(format_item('gmail', env)['sender'], '', msg=f'from={frm!r}')


class ListUnreadTests(unittest.TestCase):
    def test_normal(self):
        payload = json.dumps({'envelopes': [
            {'id': 1, 'from': [{'name': 'Alice', 'email': 'a@x.com'}], 'subject': 'Hi', 'date': '2026-09-10T00:00:00Z'},
        ]}).encode()
        result = list_unread('gmail', 5, _run=fake_runner(payload))
        self.assertTrue(result['ok'])
        self.assertEqual(result['account'], 'gmail')
        self.assertEqual(len(result['unread']), 1)
        self.assertEqual(result['unread'][0]['subject'], 'Hi')
        self.assertEqual(result['unread'][0]['sender'], 'Alice')

    def test_empty(self):
        result = list_unread('ucsb', 5, _run=fake_runner(b'{"envelopes":[]}'))
        self.assertTrue(result['ok'])
        self.assertEqual(result['unread'], [])

    def test_chinese_fields(self):
        payload = json.dumps({'envelopes': [
            {'id': 1, 'from': [{'name': '网易', 'email': 'm@x.com'}], 'subject': '提醒', 'date': '2026-09-10T17:32:46+08:00'},
        ]}, ensure_ascii=False).encode('utf-8')
        result = list_unread('163', 5, _run=fake_runner(payload))
        self.assertEqual(result['unread'][0]['sender'], '网易')
        self.assertEqual(result['unread'][0]['subject'], '提醒')

    def test_invalid_account_and_limit_rejected_before_run(self):
        with self.assertRaises(MailError):
            list_unread('evil', 5, _run=fake_runner())
        with self.assertRaises(MailError):
            list_unread('gmail', 0, _run=fake_runner())
        with self.assertRaises(MailError):
            list_unread('gmail', 21, _run=fake_runner())

    def test_parameter_injection_rejected(self):
        # account/limit must never become arbitrary args to the subprocess
        for account in ('gmail --config /etc/passwd', 'gmail; ls', '"gmail"', "gmail' OR 1=1--"):
            with self.subTest(account=account), self.assertRaises(MailError):
                list_unread(account, 5, _run=fake_runner())
        for limit in ('5 --page-size 9999', '5; rm', 5.5):
            with self.subTest(limit=limit), self.assertRaises(MailError):
                list_unread('gmail', limit, _run=fake_runner())

    def test_process_failure_raises_mail_error(self):
        def _run(cmd, timeout, max_bytes):
            raise MailError('himalaya 执行失败。')
        with self.assertRaises(MailError):
            list_unread('gmail', 5, _run=_run)


class CollectLimitedTests(unittest.TestCase):
    def test_normal_collects_stdout_and_stderr(self):
        proc = make_proc(stdout=b'{"envelopes":[]}', stderr=b'warning')
        self.addCleanup(proc.close)
        out, err = collect_limited(proc, 5.0, 65536)
        self.assertEqual(out, b'{"envelopes":[]}')
        self.assertEqual(err, b'warning')
        self.assertEqual(proc.returncode, 0)

    def test_timeout_aborts(self):
        proc = make_proc(keep_stdout_open=True)
        self.addCleanup(proc.close)
        with self.assertRaisesRegex(MailError, '超时'):
            collect_limited(proc, 0.05, 65536)

    def test_output_overflow_aborts(self):
        proc = make_proc(stdout=b'x' * 4096)
        self.addCleanup(proc.close)
        with self.assertRaisesRegex(MailError, '上限'):
            collect_limited(proc, 5.0, 100)

    def test_overflow_kills_process(self):
        proc = make_proc(stdout=b'x' * 4096)
        self.addCleanup(proc.close)
        with self.assertRaises(MailError):
            collect_limited(proc, 5.0, 100)


class HardeningTests(unittest.TestCase):
    def test_local_result_limit_and_strict_fields(self):
        payload = json.dumps({'envelopes': [{'id': True, 'from': [{'name': {}, 'email': []}]}] * 10}).encode()
        result = list_unread('gmail', 2, _run=fake_runner(payload))
        self.assertEqual(len(result['unread']), 2)
        self.assertIsNone(result['unread'][0]['id'])
        self.assertEqual(result['unread'][0]['sender'], '')

    def test_eof_still_obeys_timeout(self):
        import subprocess, sys, time
        proc = subprocess.Popen([sys.executable, '-c', 'import os,time; os.close(1); os.close(2); time.sleep(30)'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        proc._aion_process_group = True
        start = time.monotonic()
        try:
            with self.assertRaisesRegex(MailError, '超时'):
                collect_limited(proc, 0.2, 100)
            self.assertLess(time.monotonic() - start, 3)
            self.assertIsNotNone(proc.poll())
            self.assertTrue(proc.stdout.closed and proc.stderr.closed)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=2)

    def test_read_error_is_sanitized_and_cleans_streams(self):
        from unittest.mock import patch
        proc = make_proc(stdout=b'x')
        with patch('sdk_mail.os.read', side_effect=OSError('private diagnostic')):
            with self.assertRaises(MailError) as caught:
                collect_limited(proc, 1, 100)
        self.assertNotIn('private diagnostic', str(caught.exception))
        self.assertIsNotNone(proc.returncode)
        self.assertTrue(proc.stdout.closed and proc.stderr.closed)

class ErrorCodeTests(unittest.TestCase):
    def test_known_failures_have_safe_codes(self):
        from unittest.mock import patch
        with self.assertRaises(MailError) as invalid:
            parse_envelopes(b'private non-json diagnostic')
        self.assertEqual(invalid.exception.code, 'invalid_json')
        with patch('sdk_mail.subprocess.Popen', side_effect=OSError('private credential')):
            with self.assertRaises(MailError) as launch:
                sdk_mail._run_himalaya([], 1, 100)
        self.assertEqual(launch.exception.code, 'launch_failed')
        self.assertNotIn('private', str(launch.exception))
        proc = make_proc(keep_stdout_open=True)
        self.addCleanup(proc.close)
        with self.assertRaises(MailError) as timeout:
            collect_limited(proc, 0.01, 100)
        self.assertEqual(timeout.exception.code, 'timeout')

class SchoolAccountTests(unittest.TestCase):
    def test_school_identity_resolves_to_local_alias(self):
        calls = []
        def runner(cmd, timeout, max_bytes):
            calls.append(cmd)
            return b'{"envelopes":[{"id":"1","subject":"School fixture"}]}'
        result = list_unread('school', 3, _run=runner)
        self.assertEqual(result['account'], 'school')
        self.assertEqual(calls[0][calls[0].index('-a') + 1], 'ucsb')
        self.assertNotIn('gmail', calls[0])
        self.assertFalse(result['body_read'])
        self.assertEqual(result['summary_basis'], 'envelope_metadata_only')

    def test_process_error_does_not_leak_stderr(self):
        from unittest.mock import patch
        proc = make_proc(stderr=b'SECRET_FIXTURE /private/credential', returncode=1)
        self.addCleanup(proc.close)
        with patch('sdk_mail.subprocess.Popen', return_value=proc):
            with self.assertRaises(MailError) as error:
                sdk_mail._run_himalaya(build_command('school', 3), 1, 65536)
        self.assertEqual(error.exception.code, 'process_failed')
        self.assertNotIn('SECRET_FIXTURE', str(error.exception))
        self.assertNotIn('/private', str(error.exception))


if __name__ == '__main__':
    unittest.main()
