#requires -Version 7.0
$ErrorActionPreference = 'Stop'
$source = Get-Content (Join-Path $PSScriptRoot 'start-local.ps1') -Raw
$errors = $null; $tokens = $null
$null = [Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Launcher syntax failed' }
$code = [regex]::Match($source, "(?s)Add-Type -TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
Add-Type -TypeDefinition $code
$valid = 'CONTACT_DIAG request_id=' + ('a' * 32) + ' stage=smtp_auth code=smtp_auth_failed'
if (-not [ContactDiagnosticPump]::Allowed($valid)) { throw 'Valid event rejected' }
foreach ($bad in @('PRIVATE', "$valid PRIVATE", ($valid.Replace('smtp_auth_failed','private')), ($valid.Replace(('a'*32),'email@example.test')))) {
    if ([ContactDiagnosticPump]::Allowed($bad)) { throw 'Unsafe event accepted' }
}
$inputText = 'PRIVATE' + "`n" + ('x' * 10000) + "`n" + $valid + "`n"
$stream = [IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($inputText))
$reader = [IO.StreamReader]::new($stream)
$writer = [IO.StringWriter]::new()
try { [ContactDiagnosticPump]::Run($reader, $writer).GetAwaiter().GetResult() } finally { $reader.Dispose() }
if ($writer.ToString().Trim() -ne $valid) { throw 'Stream filtering failed' }
Write-Host 'PASS: syntax, allowlist, secret rejection, oversized-line discard, valid event after invalid data.'

$prefix = 'CONTACT_DIAG request_id=' + ('a' * 32) + ' stage=turnstile code=turnstile_'
foreach ($code in @('tls_failed','connect_timeout','read_timeout','connection_failed','response_too_large','invalid_json','http_non_200 http_status=403')) {
    if (-not [ContactDiagnosticPump]::Allowed($prefix + $code)) { throw 'New category rejected' }
}
foreach ($code in @('communication_failed','http_non_200','http_non_200 http_status=200','http_non_200 http_status=600','http_non_200 http_status=403 PRIVATE','tls_failed http_status=403')) {
    if ([ContactDiagnosticPump]::Allowed($prefix + $code)) { throw 'Invalid category/status accepted' }
}
Write-Host 'PASS: Turnstile categories and HTTP status restrictions.'

$http = $prefix + 'http_non_200 http_status=400'
foreach ($provider in @('missing-input-secret','invalid-input-secret','missing-input-response','invalid-input-response','bad-request','timeout-or-duplicate','internal-error')) {
    if (-not [ContactDiagnosticPump]::Allowed($http + ' cloudflare_code=' + $provider)) { throw 'Provider code rejected' }
}
foreach ($suffix in @('PRIVATE', 'bad-request PRIVATE', "bad-request`nPRIVATE", 'bad-request,internal-error', '')) {
    if ([ContactDiagnosticPump]::Allowed($http + ' cloudflare_code=' + $suffix)) { throw 'Unsafe provider code accepted' }
}
if ([ContactDiagnosticPump]::Allowed($prefix + 'tls_failed cloudflare_code=bad-request')) { throw 'Provider code on wrong event' }
Write-Host 'PASS: Cloudflare code allowlist and injection rejection.'
