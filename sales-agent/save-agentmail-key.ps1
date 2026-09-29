$ErrorActionPreference = 'Stop'
$salesKeyInput = Read-Host 'AgentMail APIキーを貼り付けてEnter' -AsSecureString
$salesKey = [System.Net.NetworkCredential]::new('', $salesKeyInput).Password.Trim()
if ([string]::IsNullOrWhiteSpace($salesKey) -or $salesKey -match '[\r\n]') { throw 'APIキーを確認してください。' }
$salesEnvFile = Join-Path $PSScriptRoot '.env'
$salesLines = if (Test-Path -LiteralPath $salesEnvFile) { @(Get-Content -LiteralPath $salesEnvFile) } else { @() }
$salesLines = @($salesLines | Where-Object { $_ -notmatch '^\s*AGENTMAIL_API_KEY\s*=' })
$salesLines += 'AGENTMAIL_API_KEY=' + $salesKey
[System.IO.File]::WriteAllLines($salesEnvFile, $salesLines, [System.Text.UTF8Encoding]::new($false))
$salesKey = $null
$salesLines = $null
$salesKeyInput.Dispose()
Write-Host '保存しました。チャットには「保存した」と伝えてください。'
