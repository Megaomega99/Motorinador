# Ejecuta el backend desde la raíz del proyecto
# Uso: Ejecuta este script desde el Explorador (doble clic) o PowerShell.
# Nota: puede pedir permiso para ejecutar scripts; usa `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` si hace falta.

Push-Location $PSScriptRoot
try {
    $conda = 'C:\ProgramData\miniconda3\Scripts\conda.exe'
    if (-not (Test-Path $conda)) {
        Write-Error "No se encontró conda en $conda. Ajusta la ruta en este script."
        exit 1
    }
    Write-Host "Iniciando backend (backend.main) usando entorno 'base'..."
    & $conda run -n base python -m backend.main
} finally {
    Pop-Location
}