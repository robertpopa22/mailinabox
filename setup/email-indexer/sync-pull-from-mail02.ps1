# Pull live.db from MAIL02 to GES051WS for MCP consumption.
# Run via Task Scheduler every 10 minutes on GES051WS.
#
# Prereq: SSH key at $HOME\.ssh\ges-mail01 + scp/openssh client installed.
# Schedule example:
#   schtasks /Create /SC MINUTE /MO 10 /TN "EmailIndexSync" `
#     /TR "powershell -ExecutionPolicy Bypass -File D:\github\mailinabox\setup\email-indexer\sync-pull-from-mail02.ps1"

$ErrorActionPreference = 'Stop'

$Key  = "$env:USERPROFILE\.ssh\ges-mail01"
$User = 'dit2022'
$Host = '10.0.1.89'
$Src  = '/var/lib/email-indexer/live.db'
$Dst  = 'D:\ArhivaEmail\email_archive_live.db'
$Tmp  = "$Dst.tmp"
$Log  = 'D:\ArhivaEmail\sync-pull.log'

function Log($msg) {
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
  Add-Content -Path $Log -Value $line
}

try {
  # SCP into tmp, then atomic rename to avoid partial-read during MCP query
  & scp -i $Key -o StrictHostKeyChecking=accept-new "${User}@${Host}:$Src" $Tmp
  if ($LASTEXITCODE -ne 0) { throw "scp exit $LASTEXITCODE" }
  Move-Item -Path $Tmp -Destination $Dst -Force
  Log "OK ($([math]::Round((Get-Item $Dst).Length/1MB,1)) MB)"
} catch {
  Log "FAIL: $_"
  exit 1
}
