# Registra i due giri giornalieri del radar casa (8:00 e 19:00).
# Se a quell'ora il PC e' spento, il giro parte appena si riaccende.
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$py  = Join-Path $dir ".venv\Scripts\python.exe"
$az  = New-ScheduledTaskAction -Execute $py -Argument "run.py" -WorkingDirectory $dir
$tr  = @(
  New-ScheduledTaskTrigger -Daily -At 08:00
  New-ScheduledTaskTrigger -Daily -At 19:00
)
$imp = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "Radar casa" -Action $az -Trigger $tr -Settings $imp -Description "Annunci di affitto vicino a Extrapola" -Force | Out-Null
Write-Output "Operazione 'Radar casa' registrata: 8:00 e 19:00"
