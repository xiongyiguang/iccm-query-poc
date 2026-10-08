$ErrorActionPreference = 'Stop'
$url = 'http://127.0.0.1:8771'
$status = Invoke-RestMethod "$url/api/meta" -TimeoutSec 3
if ($status.runtime -ne 'Codex App Server') { throw '该端口不是本机智能体演示，未执行停止。' }
Invoke-RestMethod "$url/api/shutdown" -Method Post -ContentType 'application/json' -Headers @{'X-Local-Token'=$status.token} -Body '{}' | Out-Null
Write-Output '已停止独立智能体演示；r10不受影响。'
