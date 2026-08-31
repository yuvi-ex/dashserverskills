<#
.SYNOPSIS
    One line from nothing to ready, on Windows PowerShell.

.DESCRIPTION
    irm https://raw.githubusercontent.com/yuvi-ex/dashserverskills/main/get.ps1 | iex

    macOS, Linux and WSL users want get.sh instead:

        sh -c "$(curl -fsSL .../get.sh)"

    Like get.sh this stays deliberately thin: it clones, finds an interpreter,
    and hands over to install.py, which is the single implementation shared by
    every platform.

    Set DASHSERVER_DIR to clone somewhere other than ~/dashserverskills.
#>

$ErrorActionPreference = 'Stop'

$Repo = 'https://github.com/yuvi-ex/dashserverskills'
$Dest = if ($env:DASHSERVER_DIR) { $env:DASHSERVER_DIR }
        else { Join-Path $HOME 'dashserverskills' }

# `python3` on Windows is often the Microsoft Store stub, which exits without
# doing anything, so `python` is tried first here and the result is verified by
# actually running it rather than by trusting the name.
$Python = $null
foreach ($candidate in @('python', 'py', 'python3')) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $found) { continue }
    try {
        $version = & $found.Source '-c' 'import sys; print(sys.version_info[0])' 2>$null
        if ($LASTEXITCODE -eq 0 -and $version -eq '3') { $Python = $found.Source; break }
    } catch { continue }
}
if (-not $Python) {
    Write-Error 'Python 3 is required. Install it from https://python.org or the Microsoft Store, then re-run.'
    exit 1
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error 'git is required. Install it from https://git-scm.com, then re-run.'
    exit 1
}

if (Test-Path (Join-Path $Dest '.git')) {
    Write-Host -NoNewline "Updating $(Split-Path $Dest -Leaf) ... "
    git -C $Dest pull --quiet --ff-only 2>$null | Out-Null
    Write-Host 'done'
} else {
    Write-Host -NoNewline "Cloning $(Split-Path $Dest -Leaf) ... "
    git clone --quiet $Repo $Dest
    Write-Host 'done'
}

# Not piped or redirected: the key prompt needs the console to hide input.
& $Python (Join-Path $Dest 'install.py') @args
exit $LASTEXITCODE
