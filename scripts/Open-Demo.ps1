param([switch]$Worker,[switch]$TestEncryption)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Security
function Protect-Key([byte[]]$bytes) {
    return [Security.Cryptography.ProtectedData]::Protect($bytes,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
}
function Unprotect-Key([byte[]]$bytes) {
    return [Security.Cryptography.ProtectedData]::Unprotect($bytes,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
}
if($TestEncryption){
    $sample=[Text.Encoding]::UTF8.GetBytes('synthetic-test-not-a-key')
    $cipher=Protect-Key $sample
    $decoded=Unprotect-Key $cipher
    if([Convert]::ToBase64String($sample) -ne [Convert]::ToBase64String($decoded)){throw 'Encryption round trip failed'}
    [Array]::Clear($sample,0,$sample.Length);[Array]::Clear($decoded,0,$decoded.Length)
    Write-Output 'Windows user encryption round trip OK (synthetic data only)'
    exit
}
$root=Split-Path -Parent $PSScriptRoot
$state=Join-Path $root '.local'
$keyFile=Join-Path $state 'deepseek.key'
$runtime=Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$url='http://127.0.0.1:8765'
function Get-Demo {
    try{return Invoke-RestMethod "$url/api/meta" -TimeoutSec 2}catch{return $null}
}
try {
    if($Worker){
        $existing=Get-Demo
        if($existing -and $existing.version -and $existing.model.provider -eq 'DeepSeek'){exit}
        $cipher=[Convert]::FromBase64String([IO.File]::ReadAllText($keyFile))
        $plain=Unprotect-Key $cipher
        try{$env:DEEPSEEK_API_KEY=[Text.Encoding]::UTF8.GetString($plain)}
        finally{[Array]::Clear($plain,0,$plain.Length)}
        $env:DEEPSEEK_MODEL='deepseek-v4-flash'
        $env:PYTHONDONTWRITEBYTECODE='1'
        & $runtime (Join-Path $root 'backend\app.py') --port 8765
        if($LASTEXITCODE -ne 0){
            [IO.Directory]::CreateDirectory($state) | Out-Null
            [IO.File]::AppendAllText((Join-Path $state 'service-status.log'),([DateTime]::Now.ToString('s')+' service exited; code='+$LASTEXITCODE+"`r`n"))
        }
        exit
    }
    $running=Get-Demo
    if($running -and $running.model.provider -eq 'DeepSeek' -and $running.model.available){Start-Process $url;exit}
    if($running){throw '8765端口上已有未配置完成的服务。请先关闭原启动窗口，再双击打开演示。'}
    if(!(Test-Path -LiteralPath $keyFile)){
        $form=New-Object Windows.Forms.Form
        $form.Text='首次配置 DeepSeek';$form.Width=530;$form.Height=230;$form.StartPosition='CenterScreen';$form.TopMost=$true
        $label=New-Object Windows.Forms.Label
        $label.Text="输入官方 API 密钥，仅需配置一次。`n将加密保存到当前 Windows 用户，密钥不会发送给助手。"
        $label.SetBounds(20,20,480,50)
        $box=New-Object Windows.Forms.TextBox;$box.UseSystemPasswordChar=$true;$box.SetBounds(20,80,475,28)
        $button=New-Object Windows.Forms.Button;$button.Text='保存并打开演示';$button.SetBounds(320,125,175,32);$button.DialogResult='OK'
        $form.Controls.AddRange(@($label,$box,$button));$form.AcceptButton=$button
        if($form.ShowDialog() -ne 'OK'){$form.Dispose();exit}
        if([string]::IsNullOrWhiteSpace($box.Text)){$form.Dispose();throw '未输入密钥，请重新打开演示配置。'}
        $plain=[Text.Encoding]::UTF8.GetBytes($box.Text.Trim())
        $box.Clear();$form.Dispose()
        try{
            $cipher=Protect-Key $plain
            [IO.Directory]::CreateDirectory($state) | Out-Null
            [IO.File]::WriteAllText($keyFile,[Convert]::ToBase64String($cipher),[Text.Encoding]::ASCII)
        } finally{[Array]::Clear($plain,0,$plain.Length)}
    }
    if(!(Test-Path -LiteralPath $runtime)){throw '未找到本机Python运行时。'}
    $shell=Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $process=Start-Process -FilePath $shell -ArgumentList ('-NoProfile -WindowStyle Hidden -File "'+$PSCommandPath+'" -Worker') -WindowStyle Hidden -PassThru
    $ready=$false
    for($i=0;$i -lt 15;$i++){
        Start-Sleep -Milliseconds 500
        $m=Get-Demo
        if($m -and $m.model.provider -eq 'DeepSeek' -and $m.model.available){$ready=$true;break}
        if($process.HasExited){break}
    }
    if(!$ready){throw '后台服务未能启动，请检查端口或重新配置密钥。'}
    Start-Process $url
} catch {
    if($Worker){
        [IO.Directory]::CreateDirectory($state) | Out-Null
        [IO.File]::AppendAllText((Join-Path $state 'service-status.log'),([DateTime]::Now.ToString('s')+' background startup failed; check runtime and encrypted configuration'+"`r`n"))
    }else{
        [Windows.Forms.MessageBox]::Show($_.Exception.Message,'iCCM 演示启动提示','OK','Error') | Out-Null
    }
} finally {if($Worker){$env:DEEPSEEK_API_KEY=$null}}