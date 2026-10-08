param([switch]$RefreshKeys)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$toolDirectory = $PSScriptRoot
$extractorDirectory = Join-Path $toolDirectory 'fmodel'
$extractor = Join-Path $extractorDirectory 'FModelCLI.exe'
$expectedHash = '86426493c63f0af2ccf6d1d8b498a737723069f6c25a573a46e94d1a3f26e835'
$extractorUrl = 'https://github.com/Herselfta/FModelCLI/releases/download/v1.0.2/FModelCLI.exe'
New-Item -ItemType Directory -Path $extractorDirectory -Force | Out-Null

function Get-Sha256([string]$path) {
    $stream = [IO.File]::OpenRead($path)
    $digest = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($digest.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
    } finally {
        $digest.Dispose()
        $stream.Dispose()
    }
}

if (Test-Path -LiteralPath $extractor) {
    if ((Get-Sha256 $extractor) -ne $expectedHash) {
        throw 'Existing FModelCLI.exe does not match the pinned release. Move it aside and retry.'
    }
} else {
    $download = "$extractor.download"
    try {
        Invoke-WebRequest -Uri $extractorUrl -OutFile $download -UseBasicParsing
        if ((Get-Sha256 $download) -ne $expectedHash) {
            throw 'Downloaded FModelCLI.exe failed SHA-256 verification.'
        }
        Move-Item -LiteralPath $download -Destination $extractor
    } finally {
        if (Test-Path -LiteralPath $download) { Remove-Item -LiteralPath $download }
    }
}
Write-Host 'FModelCLI v1.0.2: SHA-256 verified.'

$keyFile = Join-Path $toolDirectory 'pakkeys.txt'
if ($RefreshKeys -or -not (Test-Path -LiteralPath $keyFile)) {
    $response = Invoke-RestMethod -Uri 'https://raw.githubusercontent.com/yarik0chka/wuwa-keys/main/keys.json'
    $keys = @($response.mainKey) + @($response.dynamicKeys | ForEach-Object { $_.key })
    $keys = @($keys | Select-Object -Unique)
    if ($keys.Count -eq 0) { throw 'No resource keys returned.' }
    foreach ($key in $keys) {
        if ($key -notmatch '^0x[0-9a-fA-F]{64}$') { throw 'Invalid resource key format.' }
    }
    $temporaryKeys = "$keyFile.tmp"
    try {
        [IO.File]::WriteAllLines($temporaryKeys, [string[]]$keys, [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporaryKeys -Destination $keyFile -Force
    } finally {
        if (Test-Path -LiteralPath $temporaryKeys) { Remove-Item -LiteralPath $temporaryKeys }
    }
    Write-Host "Resource keys prepared: $($keys.Count)."
} else {
    Write-Host 'Existing resource keys retained. Use -RefreshKeys after a game update.'
}
Write-Host 'Tools are ready. No game files were changed.'
