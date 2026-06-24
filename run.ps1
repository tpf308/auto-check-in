# AnyRouter local daily check-in launcher (invoked by Task Scheduler).
# Python owns checkin.log exclusively; launcher errors go to launcher-error.log.
$dir = $PSScriptRoot
$py  = Join-Path $dir '.venv\Scripts\python.exe'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
& $py (Join-Path $dir 'scripts\anyrouter_local_checkin.py') 2> (Join-Path $dir 'launcher-error.log')
exit $LASTEXITCODE
