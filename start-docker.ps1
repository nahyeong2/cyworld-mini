$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker 紐낅졊??李얠쓣 ???놁뒿?덈떎. Docker Desktop???ㅽ뻾???????곕??먯뿉???ㅼ떆 ?쒕룄?섏꽭??"
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker ?붿쭊???곌껐?????놁뒿?덈떎. Docker Desktop??以鍮꾨맆 ?뚭퉴吏 湲곕떎由????ㅼ떆 ?쒕룄?섏꽭??"
}

if (-not (Test-Path -LiteralPath ".env")) {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()

    function New-Base64Url([int]$Size) {
        $bytes = New-Object byte[] $Size
        $rng.GetBytes($bytes)
        return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    }

    $secretKey = New-Base64Url 64
    $totpKey = (New-Base64Url 32) + "="
    @(
        "SECRET_KEY=$secretKey"
        "TOTP_ENCRYPTION_KEY=$totpKey"
    ) | Set-Content -LiteralPath ".env" -Encoding ascii
    $rng.Dispose()
    Write-Host "Docker ?꾩슜 蹂댁븞 ?ㅻ? ?앹꽦?덉뒿?덈떎." -ForegroundColor Green
}

docker compose up --build -d
if ($LASTEXITCODE -ne 0) {
    throw "Docker ?대?吏 鍮뚮뱶 ?먮뒗 而⑦뀒?대꼫 ?ㅽ뻾???ㅽ뙣?덉뒿?덈떎."
}

docker compose ps
Write-Host ""
Write-Host "Miniroom Docker ?ㅽ뻾 ?꾨즺: http://127.0.0.1:8000" -ForegroundColor Cyan
Start-Process "http://127.0.0.1:8000"
