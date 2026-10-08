param([int]$Port=8765,[switch]$ConfigureKey)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$runtime=Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if(!(Test-Path -LiteralPath $runtime)){throw '未找到本机Codex配套Python运行时'}
if($ConfigureKey){
    $secret=Read-Host '请输入DeepSeek官方API密钥（输入隐藏，仅用于当前进程）' -AsSecureString
    $ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    try{$env:DEEPSEEK_API_KEY=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)}
    finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr);$secret.Dispose()}
}
if(!$env:DEEPSEEK_API_KEY){Write-Warning '尚未配置DeepSeek密钥。可用 -ConfigureKey 参数启动并隐藏输入；当前仅可引导查询。'}
if(!$env:DEEPSEEK_MODEL){$env:DEEPSEEK_MODEL='deepseek-v4-flash'}
Write-Host "模型：$env:DEEPSEEK_MODEL （DeepSeek官方API，非思考模式）"
Write-Host "打开 http://127.0.0.1:$Port ，停止服务请按 Ctrl+C。"
$env:PYTHONDONTWRITEBYTECODE='1'
try{& $runtime (Join-Path $root 'backend\app.py') --port $Port}
finally{if($ConfigureKey){$env:DEEPSEEK_API_KEY=$null}}
