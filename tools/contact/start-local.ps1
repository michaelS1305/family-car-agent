#requires -Version 7.0
[CmdletBinding()]
param([switch]$SelfTest)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$children = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()
$secretValues = @{}

# Bounded streaming filter: never forward arbitrary child output or exceptions.
if (-not ('ContactDiagnosticPump' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
public static class ContactDiagnosticPump {
    public static bool Allowed(string line) {
        return Regex.IsMatch(line, @"\ACONTACT_DIAG request_id=[a-f0-9]{32} stage=(?:configuration code=configuration_invalid|turnstile code=turnstile_(?:tls_failed|connect_timeout|read_timeout|connection_failed|response_too_large|invalid_json|rejected|http_non_200 http_status=(?!200)[1-5][0-9]{2}(?: cloudflare_code=(?:missing-input-secret|invalid-input-secret|missing-input-response|invalid-input-response|bad-request|timeout-or-duplicate|internal-error))?)|smtp_connect code=smtp_connect_failed|smtp_auth code=smtp_auth_failed|smtp_send code=(?:smtp_rejected|delivery_uncertain)|request code=(?:unexpected_failure|request_incomplete))\z");
    }
    public static async Task Run(StreamReader reader, TextWriter output = null) {
        var line = new StringBuilder(); var buffer = new char[128]; bool discard = false;
        try {
            int count;
            while ((count = await reader.ReadAsync(buffer, 0, buffer.Length)) > 0) {
                for (int i=0; i<count; i++) {
                    char c = buffer[i];
                    if (c == '\n') {
                        string value = line.ToString().TrimEnd('\r');
                        if (!discard && Allowed(value)) { try { (output ?? Console.Out).WriteLine(value); } catch { } }
                        line.Clear(); discard=false;
                    } else if (!discard) {
                        if (line.Length >= 256) { line.Clear(); discard=true; }
                        else line.Append(c);
                    }
                }
            }
        } catch { /* No raw diagnostics; transport failure must not block the server. */ }
    }
}
'@
}

function Read-Masked([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer); $secure.Dispose() }
}

function Start-Isolated([string]$Exe, [string[]]$Arguments, [string]$Directory, [hashtable]$Variables, [switch]$ContactDiagnostics) {
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $Exe
    $info.WorkingDirectory = $Directory
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    # Never inherit cloud/database credentials or CONTACT secrets into Vite.
    $info.Environment.Clear()
    foreach ($key in @('SystemRoot','WINDIR','PATH','TEMP','TMP','USERPROFILE','APPDATA','LOCALAPPDATA')) {
        $value = [Environment]::GetEnvironmentVariable($key)
        if ($value) { $info.Environment[$key] = $value }
    }
    foreach ($key in $Variables.Keys) { $info.Environment[$key] = $Variables[$key] }
    foreach ($argument in $Arguments) { $info.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $info
    if (-not $process.Start()) { throw 'Child startup failed.' }
    $children.Add($process)
    # Drain without retaining or displaying raw diagnostics (including provider errors).
    if ($ContactDiagnostics) { $null = [ContactDiagnosticPump]::Run($process.StandardOutput, [Console]::Out) }
    else { $null = $process.StandardOutput.BaseStream.CopyToAsync([IO.Stream]::Null) }
    $null = $process.StandardError.BaseStream.CopyToAsync([IO.Stream]::Null)
    $info.Environment.Clear()
    return $process
}

function Wait-Ready([string]$Url, [Diagnostics.Process]$Process) {
    for ($i = 0; $i -lt 60; $i++) {
        if ($Process.HasExited) { throw 'Local process exited before readiness.' }
        try {
            $response = Invoke-WebRequest $Url -NoProxy -TimeoutSec 5 -SkipHttpErrorCheck
            if ($response.StatusCode -eq 200) { return $response }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    throw 'Local readiness timed out.'
}

try {
    $python = Join-Path $root '.venv/Scripts/python.exe'
    if (-not (Test-Path $python)) { throw 'Project .venv Python is missing. Install dependencies separately.' }
    $node = (Get-Command node -ErrorAction Stop).Source
    $null = Get-Command pnpm -ErrorAction Stop
    $vite = Join-Path $root 'website/node_modules/vite/bin/vite.js'
    if (-not (Test-Path $vite)) { throw 'Website dependencies missing. Run pnpm install separately.' }
    foreach ($port in @(8000,5173)) {
        $probe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $port)
        try { $probe.Start() } finally { $probe.Stop() }
    }
    $check = Start-Isolated $python @('-c','import sys,uvicorn,fastapi,requests,python_multipart,contact_local; assert sys.version_info >= (3,11)') (Join-Path $root 'backend') @{}
    if (-not $check.WaitForExit(15000) -or $check.ExitCode -ne 0) { throw 'Python/contact dependency check failed.' }
    if ($SelfTest) {
        $secretValues = @{CONTACT_SMTP_USERNAME='synthetic@example.test'; CONTACT_SMTP_PASSWORD='synthetic-password'; CONTACT_TURNSTILE_SECRET='synthetic-secret'}
        $siteKey = 'synthetic-public-key'
    } else {
        $secretValues.CONTACT_SMTP_USERNAME = Read-Masked 'Primary Zoho mailbox (hidden)'
        $secretValues.CONTACT_SMTP_PASSWORD = Read-Masked 'Zoho App Password (hidden)'
        $secretValues.CONTACT_TURNSTILE_SECRET = Read-Masked 'Turnstile private secret (hidden)'
        $siteKey = Read-Host 'Turnstile public site key (localhost widget)'
    }
    if (-not $siteKey.Trim() -or @($secretValues.Values | Where-Object { -not $_ }).Count) { throw 'Required configuration missing.' }
    $backendEnv = @{
        CONTACT_ENABLED='true'; CONTACT_SMTP_HOST='smtppro.zoho.com'; CONTACT_SMTP_PORT='465'
        CONTACT_FROM_EMAIL='support@familycaragent.com'; CONTACT_TO_EMAIL='support@familycaragent.com'
        CONTACT_SMTP_TIMEOUT='10'; CONTACT_TURNSTILE_HOSTNAME='localhost'; PYTHON_DOTENV_DISABLED='1'
    }
    foreach ($key in $secretValues.Keys) { $backendEnv[$key] = $secretValues[$key] }
    if ($SelfTest) {
        $envCheck = Start-Isolated $python @('-c', 'import os; from contact_mail import Config; assert Config.load() is not None; assert not any(k.startswith("VITE_") for k in os.environ)') (Join-Path $root 'backend') $backendEnv
        if (-not $envCheck.WaitForExit(15000) -or $envCheck.ExitCode -ne 0) { throw 'Backend environment isolation failed.' }
        $envCheck = Start-Isolated $node @('-e', 'if(Object.keys(process.env).some(k=>k.startsWith("CONTACT_")||k==="DATABASE_URL"))process.exit(1);if(!process.env.VITE_TURNSTILE_SITE_KEY)process.exit(1)') (Join-Path $root 'website') @{VITE_TURNSTILE_SITE_KEY=$siteKey}
        if (-not $envCheck.WaitForExit(15000) -or $envCheck.ExitCode -ne 0) { throw 'Frontend environment isolation failed.' }
    }
    $backend = Start-Isolated $python @('-m','uvicorn','contact_local:app','--host','127.0.0.1','--port','8000','--no-proxy-headers','--no-access-log') (Join-Path $root 'backend') $backendEnv -ContactDiagnostics
    $backendEnv.Clear(); $secretValues.Clear()
    # Equivalent to the existing pnpm dev command, with fixed port and no shell child.
    $frontend = Start-Isolated $node @($vite,'--host','127.0.0.1','--port','5173','--strictPort') (Join-Path $root 'website') @{
        VITE_CONTACT_API_BASE_URL='http://127.0.0.1:8000'; VITE_TURNSTILE_SITE_KEY=$siteKey
    }
    Write-Host 'Checking backend readiness...'
    $health = (Wait-Ready 'http://127.0.0.1:8000/health' $backend).Content | ConvertFrom-Json
    if ($health.service -ne 'contact-local' -or -not $health.configured) { throw 'Contact configuration check failed.' }
    Write-Host 'Checking website readiness...'
    $null = Wait-Ready 'http://localhost:5173/contact' $frontend
    $cors = Invoke-WebRequest 'http://127.0.0.1:8000/api/contact' -NoProxy -TimeoutSec 3 -Method Options -Headers @{
        Origin='http://localhost:5173'; 'Access-Control-Request-Method'='POST'; 'Access-Control-Request-Headers'='content-type'
    }
    if ($cors.Headers['Access-Control-Allow-Origin'] -ne 'http://localhost:5173') { throw 'CORS check failed.' }
    $route = Invoke-WebRequest 'http://127.0.0.1:8000/api/contact' -NoProxy -TimeoutSec 3 -SkipHttpErrorCheck
    if ($route.StatusCode -ne 405) { throw 'Contact route check failed.' }
    Write-Host 'PASS: local backend, website, configuration presence and CORS. No submission sent.'
    Write-Host 'Website: http://localhost:5173/contact'
    Write-Host 'SMTP connectivity/alias authorization and real Turnstile initialization are NOT verified.'
    if (-not $SelfTest) {
        Write-Host 'Do not submit yet. Open the page to inspect the widget. Press Ctrl+C to stop.'
        while (-not $backend.HasExited -and -not $frontend.HasExited) { Start-Sleep -Seconds 1 }
    }
} catch {
    # Do not print exceptions: child/configuration errors may contain sensitive data.
    Write-Host 'FAIL: local setup/readiness. Check dependencies and free ports; no raw diagnostics displayed.'
    exit 1
} finally {
    foreach ($child in $children) {
        try { if (-not $child.HasExited) { $child.Kill($true); $child.WaitForExit(5000) | Out-Null } }
        finally { $child.Dispose() }
    }
    $secretValues.Clear()
    if ($backendEnv) { $backendEnv.Clear() }
    Write-Host 'Local child processes stopped; no credentials written to files.'
}
