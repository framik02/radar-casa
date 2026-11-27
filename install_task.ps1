# Registra i due giri giornalieri del radar casa (8:00 e 19:00).
# Se a quell'ora il PC e' spento, il giro parte appena si riaccende.
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$py  = Join-Path $dir ".venv\Scripts\pythonw.exe"
$az  = New-ScheduledTaskAction -Execute $py -Argument "run.py" -WorkingDirectory $dir
$tr  = @(
  New-ScheduledTaskTrigger -Daily -At 08:00
  New-ScheduledTaskTrigger -Daily -At 19:00
)
$imp = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "Radar casa" -Action $az -Trigger $tr -Settings $imp -Description "Annunci di affitto vicino a Extrapola" -Force | Out-Null
Write-Output "Operazione 'Radar casa' registrata: 8:00 e 19:00"

# Ogni 5 minuti legge le richieste di giro dal telefono (tasto Aggiorna o /aggiorna al bot)
$az2 = New-ScheduledTaskAction -Execute $py -Argument "ascolta.py" -WorkingDirectory $dir
$tr2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$imp2 = New-ScheduledTaskSettingsSet -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Radar casa ascolto" -Action $az2 -Trigger $tr2 -Settings $imp2 -Description "Richieste di giro dal telefono" -Force | Out-Null
