param(
    [Parameter(Mandatory=$true)][string]$Target,
    [string]$ShortcutArgs = "",
    [string]$WorkDir = "",
    [string]$Icon = "",
    [string]$Name = "Luno Launcher",
    [int]$WindowStyle = 1
)
$desktop = [Environment]::GetFolderPath('Desktop')
$link = Join-Path $desktop ($Name + ".lnk")
$sh = New-Object -ComObject WScript.Shell
$s = $sh.CreateShortcut($link)
$s.TargetPath = $Target
if ($ShortcutArgs) { $s.Arguments = $ShortcutArgs }
if ($WorkDir) { $s.WorkingDirectory = $WorkDir }
if ($Icon -and (Test-Path $Icon)) { $s.IconLocation = $Icon } else { $s.IconLocation = $Target }
$s.WindowStyle = $WindowStyle
$s.Save()
Write-Host "Desktop shortcut created: $link"
