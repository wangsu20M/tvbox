$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

# GitHub access may use the local proxy, but stream checks explicitly bypass it.
$gitArgs = @(
    "-c", "http.proxy=http://127.0.0.1:10808",
    "-c", "https.proxy=http://127.0.0.1:10808"
)

& git @gitArgs fetch origin main
& git merge --ff-only origin/main
& python local_filter.py

& git add public/live.m3u public/tvbox.json
& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    & git commit -m "chore: update mainland-verified streams"
    & git @gitArgs push origin HEAD:main
}
