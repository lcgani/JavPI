param(
    [Parameter(Mandatory=$true)] [string]$ProjectId,
    [string]$Region = "us-central1",
    [string]$ServiceName = "javpi-backend",
    [string]$FirestoreLocation = "nam5",
    [string]$BackendApiKey = "",
    [string]$FirestoreCollection = "javpi_sessions",
    [switch]$AllowUnauthenticated
)

$ErrorActionPreference = "Stop"

function Get-GcloudCmd {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"),
        "C:\Program Files\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
    )
    foreach ($p in $candidates) {
        if ($p -and (Test-Path $p)) {
            return $p
        }
    }

    $cmd = Get-Command gcloud.cmd -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    throw "gcloud.cmd not found. Install Google Cloud CLI and ensure gcloud.cmd is available."
}

$gcloud = Get-GcloudCmd

function Invoke-GcloudChecked {
    param([Parameter(ValueFromRemainingArguments=$true)] [string[]]$Args)
    & $gcloud @Args
    if ($LASTEXITCODE -ne 0) {
        throw "gcloud failed (exit $LASTEXITCODE): gcloud $($Args -join ' ')"
    }
}

Write-Host "[1/5] Setting project"
Invoke-GcloudChecked config set project $ProjectId | Out-Null

Write-Host "[2/5] Enabling required services"
Invoke-GcloudChecked services enable `
  run.googleapis.com `
  cloudbuild.googleapis.com `
  artifactregistry.googleapis.com `
  firestore.googleapis.com

Write-Host "[3/5] Ensuring Firestore database exists"
$existing = & $gcloud firestore databases list --format="value(name)" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "gcloud failed (exit $LASTEXITCODE): gcloud firestore databases list"
}
if (-not $existing) {
  Invoke-GcloudChecked firestore databases create --location=$FirestoreLocation --type=firestore-native
}

if ($AllowUnauthenticated -and -not $BackendApiKey) {
  throw "Refusing public deploy without BackendApiKey. Provide -BackendApiKey or omit -AllowUnauthenticated."
}

Write-Host "[4/5] Deploying Cloud Run service"
$envVars = "GOOGLE_CLOUD_PROJECT=$ProjectId,JAVPI_FIRESTORE_COLLECTION=$FirestoreCollection"
if ($BackendApiKey) {
  $envVars = "$envVars,JAVPI_BACKEND_API_KEY=$BackendApiKey"
}

$deployArgs = @(
  "run", "deploy", $ServiceName,
  "--source", ".",
  "--region", $Region,
  "--set-env-vars", $envVars
)
if ($AllowUnauthenticated) {
  Write-Host "Deploy mode: public (API key required by script guard)."
  $deployArgs += "--allow-unauthenticated"
} else {
  Write-Host "Deploy mode: authenticated only (recommended)."
  $deployArgs += "--no-allow-unauthenticated"
}

Push-Location backend
try {
  Invoke-GcloudChecked @deployArgs
}
finally {
  Pop-Location
}

Write-Host "[5/5] Reading service URL"
$serviceUrl = & $gcloud run services describe $ServiceName --region $Region --format="value(status.url)"
if ($LASTEXITCODE -ne 0) {
    throw "gcloud failed (exit $LASTEXITCODE): gcloud run services describe"
}
Write-Host "Deployed URL: $serviceUrl"
