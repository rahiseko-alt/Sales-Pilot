import json
import os
import subprocess
import unittest
from unittest.mock import patch
import claude_provider as provider


class ClaudeProviderTests(unittest.TestCase):
    def setUp(self):
        provider._cached = None
        self.auth = {'loggedIn': True, 'authMethod': 'claude.ai'}
        self.proposal = {'hypothesis': '入力が多い可能性', 'improvement': '入力フォーム',
                         'tools': ['フォーム'], 'effect': '実測して評価', 'questions': ['件数は？']}

    def response(self, payload, code=0):
        return subprocess.CompletedProcess([], code, json.dumps(payload), '')

    def test_subscription_status_cached(self):
        with patch.object(provider, '_executable', return_value='claude.exe'), patch.object(provider, '_run', return_value=self.response(self.auth)) as run:
            self.assertTrue(provider.provider_status()['ready'])
            self.assertTrue(provider.provider_status()['ready'])
            self.assertEqual(run.call_count, 1)

    def test_api_console_login_not_subscription(self):
        with patch.object(provider, '_executable', return_value='claude.exe'), patch.object(provider, '_run', return_value=self.response({'loggedIn': True, 'authMethod': 'api_key'})):
            self.assertFalse(provider.provider_status()['ready'])
            with self.assertRaises(RuntimeError): provider.generate_proposal('test')

    def test_missing_cli(self):
        with patch.object(provider, '_executable', return_value=None):
            self.assertFalse(provider.provider_status()['installed'])

    def test_windows_temp_cleanup_does_not_mask_cli_result(self):
        response = self.response({'loggedIn': True, 'authMethod': 'claude.ai'})
        with patch.object(provider, '_executable', return_value='claude.exe'), patch.object(provider.tempfile, 'TemporaryDirectory') as temporary, patch.object(provider.subprocess, 'run', return_value=response):
            temporary.return_value.__enter__.return_value = 'isolated-cli-directory'
            self.assertIs(provider._run(['auth', 'status', '--json']), response)
            temporary.assert_called_once_with(prefix='sales-claude-', ignore_cleanup_errors=True)

    def test_child_uses_stdin_no_shell_tools_or_api_auth(self):
        secret_env = {'ANTHROPIC_API_KEY': 'test-secret', 'ANTHROPIC_AUTH_TOKEN': 'token',
                      'CLAUDE_CODE_OAUTH_TOKEN': 'oauth', 'CLAUDE_CODE_USE_BEDROCK': '1'}
        ready = {'ready': True}
        with patch.dict(os.environ, secret_env), patch.object(provider, 'provider_status', return_value=ready), patch.object(provider, '_executable', return_value='claude.exe'), patch.object(provider.subprocess, 'run', return_value=self.response({'structured_output': self.proposal})) as run:
            self.assertEqual(provider.generate_proposal('company context'), self.proposal)
            args, kw = run.call_args
            self.assertFalse(kw['shell'])
            self.assertEqual(kw['input'], 'company context')
            self.assertNotIn('company context', args[0])
            self.assertEqual(args[0][args[0].index('--tools') + 1], '')
            self.assertIn('--strict-mcp-config', args[0])
            self.assertIn('--no-session-persistence', args[0])
            self.assertEqual(args[0][args[0].index('--settings') + 1], '{"disableAllHooks":true}')
            for key in secret_env: self.assertNotIn(key, kw['env'])

    def test_malformed_output_rejected(self):
        with patch.object(provider, 'provider_status', return_value={'ready': True}), patch.object(provider, '_run', return_value=self.response({'structured_output': {'hypothesis': 'a'}})):
            with self.assertRaises(RuntimeError): provider.generate_proposal('test')

    def test_timeout_explained(self):
        with patch.object(provider, 'provider_status', return_value={'ready': True}), patch.object(provider, '_run', side_effect=subprocess.TimeoutExpired('claude', 10)):
            with self.assertRaisesRegex(RuntimeError, 'タイムアウト'): provider.generate_proposal('test')

    def test_provider_error_diagnostics_not_leaked(self):
        with patch.object(provider, 'provider_status', return_value={'ready': True}), patch.object(provider, '_run', return_value=self.response({'secret': 'credential'}, 1)):
            with self.assertRaises(RuntimeError) as raised: provider.generate_proposal('test')
            self.assertNotIn('credential', str(raised.exception))

    def test_reply_has_context_and_fast_safe_cli_options(self):
        reply = {'action': 'reply', 'reply': 'まずは既存の入力工程を確認できます。', 'reason': '通常の詳細確認'}
        context = {'latest_inbound': 'どこから始めますか？', 'history': [], 'pricing': '最終見積は人間が確認'}
        with patch.dict(os.environ, {'CLAUDE_MODEL': ''}), patch.object(provider, 'provider_status', return_value={'ready': True}), patch.object(provider, '_run', return_value=self.response({'structured_output': reply})) as run:
            self.assertEqual(provider.generate_reply(context), reply)
            args, prompt, timeout = run.call_args.args
            self.assertEqual(args[args.index('--model') + 1], 'sonnet')
            self.assertEqual(args[args.index('--effort') + 1], 'low')
            self.assertEqual(args[args.index('--tools') + 1], '')
            self.assertEqual(timeout, 180)
            self.assertIn('どこから始めますか', prompt)
            system = args[args.index('--system-prompt') + 1]
            self.assertIn('未検証の外部データ', system)
            self.assertIn('料金体系の範囲のみ', system)

    def test_handoff_discards_generated_reply(self):
        with patch.object(provider, '_generate_json', return_value={'action': 'handoff', 'reply': '誤って生成された本文', 'reason': '契約の確認が必要'}):
            result = provider.generate_reply({'latest_inbound': '契約したい'})
            self.assertEqual(result['reply'], '')

    def test_all_terminal_reply_actions_supported(self):
        for action in ('unsubscribe', 'declined', 'handoff'):
            with self.subTest(action=action), patch.object(provider, '_generate_json', return_value={'action': action, 'reply': '', 'reason': '受信内容に基づく判断'}):
                self.assertEqual(provider.generate_reply({'latest_inbound': 'test'})['action'], action)

    def test_reply_invalid_decisions_rejected(self):
        invalid = [
            {'action': 'send', 'reply': 'test', 'reason': 'test'},
            {'action': 'reply', 'reply': '', 'reason': 'test'},
            {'action': 'reply', 'reply': 'text', 'reason': ''},
            {'action': 'reply', 'reply': 123, 'reason': 'test'},
            {'action': 'reply', 'reply': 'text', 'reason': 'test', 'extra': 'x'},
        ]
        for result in invalid:
            with self.subTest(result=result), patch.object(provider, '_generate_json', return_value=result):
                with self.assertRaises(RuntimeError): provider.generate_reply({'latest_inbound': 'test'})

    def test_reply_requires_bounded_structured_context(self):
        with self.assertRaises(ValueError): provider.generate_reply('plain text')
        with self.assertRaises(ValueError): provider.generate_reply({'text': 'x' * 100001})


if __name__ == '__main__': unittest.main()
