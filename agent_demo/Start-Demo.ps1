param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$demoRoot = $PSScriptRoot
$url = 'http://127.0.0.1:8771'
try { $existing = Invoke-RestMethod "$url/api/meta" -TimeoutSec 2 } catch { $existing = $null }
if ($existing -and $existing.runtime -ne 'Codex App Server') { throw '8771端口已被其他程序占用。' }
if (-not $existing) {
    $pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
    $pythonPath = if (Test-Path 'C:\Python314\python.exe') { 'C:\Python314\python.exe' } elseif ($pythonCmd) { $pythonCmd.Source } else { throw '需要Python 3.11或更高版本。' }
    $logRoot = Join-Path (Split-Path $demoRoot) 'docs\.staging\codex-agent-demo-20260924'
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $demoProcess = Start-Process -FilePath $pythonPath -ArgumentList @('-u', ('"' + (Join-Path $demoRoot 'server.py') + '"')) -WorkingDirectory $demoRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot "$stamp-server.out.log") -RedirectStandardError (Join-Path $logRoot "$stamp-server.err.log") -PassThru
    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 750
        if ($demoProcess.HasExited) { throw "演示未启动，请检查 $logRoot 中最新日志。" }
        try { $status = Invoke-RestMethod "$url/api/meta" -TimeoutSec 2; $ready = $status.ready } catch { }
        if ($ready) { break }
    }
    if (-not $ready) { throw '启动尚未完成，请稍后重试或检查日志。' }
}
if (-not $NoBrowser) { Start-Process $url }
Write-Output "本机智能体演示：$url（r10保持不变）"
