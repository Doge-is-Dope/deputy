# Installs Python with pypdf and openpyxl for the current Windows user, with no administrator rights; safe to run again.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = 'Tls12'

# Python for the agent's commands, from python.org, and the libraries it reaches for by name: pypdf to read PDFs,
# openpyxl for spreadsheets.
$PythonVersion = '3.15.2'
$PythonSha256 = '06e225a228191b0f4d1dcf6905fbb21bf9f6970d13a2ec63137ab9bee76f15aa'
$PythonPackages = @('pypdf==7.1.0', 'openpyxl==3.1.5')
$Python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python315\python.exe'

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
    Write-Host "Python: $PythonVersion installed"
}
& $Python -m pip install --disable-pip-version-check --no-warn-script-location --quiet @PythonPackages
if ($LASTEXITCODE -ne 0) { throw "pip could not install $($PythonPackages -join ', ')." }
Write-Host "Python libraries: $($PythonPackages -join ', ')"
