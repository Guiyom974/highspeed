$ErrorActionPreference = 'Stop'
$b = 'http://127.0.0.1:8010'

Write-Host '--- /api/health'
(Invoke-RestMethod "$b/api/health") | ConvertTo-Json -Compress

Write-Host '--- /api/engine'
$e = Invoke-RestMethod "$b/api/engine"
Write-Host ("status={0} engine={1} profile={2} device={3} load={4}s calibrated={5}" -f `
  $e.status, $e.engine, $e.profile, $e.device, $e.load_seconds, $e.calibrated)

Write-Host '--- /api/stats'
$s = Invoke-RestMethod "$b/api/stats"
Write-Host ("use_cases={0} records={1} decisions={2} answers={3} busy={4}" -f `
  $s.use_case_count, $s.total_records, $s.total_decisions, $s.total_answers, $s.busy)
Write-Host ("median_latency_ms={0} best_throughput={1}/s runs_completed={2}" -f `
  $s.median_latency_ms, $s.best_throughput, $s.runs_completed)
foreach ($uc in $s.use_cases) {
  $lr = $uc.last_run
  if ($lr -and $lr.status -eq 'done') {
    $ag = ($lr.agreement.PSObject.Properties | ForEach-Object { "{0}:{1:P0}" -f $_.Name, $_.Value.agree }) -join ' '
    Write-Host ("  {0,-20} done {1}/{2}  {3}/s  med {4}ms  agree[{5}]" -f `
      $uc.key, $lr.done, $lr.total, $lr.decisions_per_second, $lr.median_latency_ms, $ag)
  } elseif ($lr) {
    Write-Host ("  {0,-20} {1} {2}/{3} {4}" -f $uc.key, $lr.status, $lr.done, $lr.total, $lr.message)
  } else {
    Write-Host ("  {0,-20} not run yet ({1} records)" -f $uc.key, $uc.record_count)
  }
}

Write-Host '--- /api/usecases'
$ucs = Invoke-RestMethod "$b/api/usecases"
Write-Host ("{0} use cases: {1}" -f $ucs.Count, (($ucs | ForEach-Object { $_.key }) -join ', '))

Write-Host '--- /api/usecases/ticket_triage (detail)'
$d = Invoke-RestMethod "$b/api/usecases/ticket_triage"
Write-Host ("questions: {0}" -f (($d.questions.PSObject.Properties | ForEach-Object { $_.Name + '(' + $_.Value.type + ')' }) -join ', '))
Write-Host ("records: {0}, with decision: {1}" -f $d.records.Count, ($d.records | Where-Object { $_.decision }).Count)
$decided = $d.records | Where-Object { $_.decision } | Select-Object -First 2
foreach ($r in $decided) {
  $dept = $r.decision.answers.department
  Write-Host ("  {0}: department={1} conf={2} routing={3} truth={4} | escalate={5} urgency={6}" -f `
    $r.ref, $dept.value, $dept.confidence, $dept.routing, $r.ground_truth.department,
    $r.decision.answers.escalate.value, $r.decision.answers.urgency.value)
}

Write-Host '--- unknown use case -> 404'
try { Invoke-RestMethod "$b/api/usecases/nope" | Out-Null; Write-Host '  [X] expected 404!' }
catch { Write-Host ("  ok: HTTP {0}" -f $_.Exception.Response.StatusCode.value__) }

Write-Host '--- export CSV'
Invoke-WebRequest "$b/api/usecases/ticket_triage/export.csv" -UseBasicParsing -OutFile "$env:TEMP\highspeed-ticket_triage.csv"
$csv = Get-Content "$env:TEMP\highspeed-ticket_triage.csv"
Write-Host ("  {0} lines, header cols: {1}" -f $csv.Count, ($csv[0] -split ',').Count)
Write-Host ("  header: {0}" -f $csv[0].Substring(0, [Math]::Min(140, $csv[0].Length)))

Write-Host '--- runs endpoints'
$latest = Invoke-RestMethod "$b/api/runs/latest"
if ($latest.id) { Write-Host ("  latest run #{0} {1} {2} {3}/{4}" -f $latest.id, $latest.use_case, $latest.status, $latest.done, $latest.total) }
else { Write-Host '  no runs yet' }

Write-Host '--- SPA index + asset'
$idx = Invoke-WebRequest "$b/" -UseBasicParsing
$asset = ([regex]::Match($idx.Content, '/assets/[^"]+\.js')).Value
$js = Invoke-WebRequest "$b$asset" -UseBasicParsing
Write-Host ("  index HTTP {0} ({1} bytes) · asset {2} HTTP {3} ({4} bytes)" -f `
  $idx.StatusCode, $idx.RawContentLength, $asset, $js.StatusCode, $js.RawContentLength)

Write-Host ''
Write-Host 'SMOKE OK'
