<#
Installs the optional parts the runtime can use on the Windows machine, for the account the runtime signs in with,
with no administrator rights (README: Windows machine). Run it as that account:

    powershell -NoProfile -ExecutionPolicy Bypass -File windows-setup.ps1 [-HostProgram <windows-tools-host.exe>] [-NoPython]

Safe to run again: what is already in place is kept.
#>
param(
    # The Windows Tools host's program, copied to where WINDOWS_TOOLS_PATH points; left as it is when not given.
    [string]$HostProgram,
    # Skip Python and its libraries.
    [switch]$NoPython
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = 'Tls12'

# Python for the agent's commands, from python.org, and the libraries it reaches for by name: pypdf to read PDFs,
# openpyxl for spreadsheets.
$PythonVersion = '3.15.2'
$PythonSha256 = '06e225a228191b0f4d1dcf6905fbb21bf9f6970d13a2ec63137ab9bee76f15aa'
$PythonPackages = @('pypdf==7.1.0', 'openpyxl==3.1.5')
$Python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python315\python.exe'
$HostPath = Join-Path $env:LOCALAPPDATA 'Programs\WindowsTools\windows-tools-host.exe'

# A running host keeps the PATH it started with and holds its program open; the runtime starts it again before the
# next desktop task.
$restartHost = $false

if ($HostProgram) {
    $source = (Resolve-Path -LiteralPath $HostProgram).Path
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "-HostProgram is not a file: $source" }
    $same = (Test-Path -LiteralPath $HostPath) -and
        (Get-FileHash -LiteralPath $source).Hash -eq (Get-FileHash -LiteralPath $HostPath).Hash
    if ($same) {
        Write-Host "Windows Tools host: already in $HostPath"
    } else {
        Get-Process windows-tools-host -ErrorAction SilentlyContinue | Stop-Process -Force
        New-Item -ItemType Directory -Force -Path (Split-Path $HostPath) | Out-Null
        Copy-Item -LiteralPath $source -Destination $HostPath -Force
        $restartHost = $true
        Write-Host "Windows Tools host: copied to $HostPath"
    }
}

if (-not $NoPython) {
    $installed = if (Test-Path -LiteralPath $Python) { (& $Python -c 'import platform; print(platform.python_version())') }
    if ($installed -eq $PythonVersion) {
        Write-Host "Python: $PythonVersion already installed"
    } else {
        # Not in TEMP: security software blocks a script from starting a program it just downloaded there.
        $installer = Join-Path (Split-Path (Split-Path $Python)) "python-$PythonVersion-amd64.exe"
        New-Item -ItemType Directory -Force -Path (Split-Path $installer) | Out-Null
        try {
            Invoke-WebRequest -UseBasicParsing -OutFile $installer `
                -Uri "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"
            if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne $PythonSha256) {
                throw "The Python installer's checksum does not match; nothing was installed."
            }
            # For this user only, on the user's PATH ahead of the Microsoft Store's python alias.
            $setup = Start-Process -FilePath $installer -Wait -PassThru -ArgumentList @(
                '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=0', 'Include_test=0', 'Shortcuts=0'
            )
            if ($setup.ExitCode -ne 0) { throw "The Python installer failed with exit code $($setup.ExitCode)." }
        } finally {
            Remove-Item -LiteralPath $installer -ErrorAction SilentlyContinue
        }
        $restartHost = $true
        Write-Host "Python: $PythonVersion installed"
    }
    & $Python -m pip install --disable-pip-version-check --no-warn-script-location --quiet @PythonPackages
    if ($LASTEXITCODE -ne 0) { throw "pip could not install $($PythonPackages -join ', ')." }
    Write-Host "Python libraries: $($PythonPackages -join ', ')"
}

if ($restartHost -and (Get-Process windows-tools-host -ErrorAction SilentlyContinue)) {
    Get-Process windows-tools-host | Stop-Process -Force
    Write-Host 'Windows Tools host: stopped; the runtime starts it again before the next desktop task'
}
