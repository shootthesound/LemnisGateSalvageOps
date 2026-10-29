# Salvage Ops map textures installer. Run through Install.bat / Uninstall.bat.
param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms

$AppId = '950180'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ShortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Lemnis Gate (Salvage Ops).lnk'
$GameIni = Join-Path $env:LOCALAPPDATA 'LemnisGate\Saved\Config\WindowsNoEditor\Game.ini'
$DevSection = '[/Script/LemnisGate.ConvergenceProjectSettings]'

function Show($text, $icon = 'Information') {
    [void][System.Windows.Forms.MessageBox]::Show($text, 'Lemnis Gate Salvage Ops', 'OK', $icon)
}

function Find-SteamGame {
    try { $steam = (Get-ItemProperty 'HKCU:\Software\Valve\Steam' -ErrorAction Stop).SteamPath } catch { return $null }
    $libs = @($steam)
    $vdf = Join-Path $steam 'steamapps\libraryfolders.vdf'
    if (Test-Path $vdf) {
        foreach ($m in (Select-String -Path $vdf -Pattern '"path"\s+"(.+)"')) {
            $libs += $m.Matches[0].Groups[1].Value -replace '\\\\', '\'
        }
    }
    foreach ($lib in $libs) {
        $g = Join-Path $lib 'steamapps\common\LemnisGate'
        if (Test-Path (Join-Path $g 'LemnisGate\Binaries\Win64\LemnisGate-Win64-Shipping.exe')) { return $g }
    }
    return $null
}

# Accepts the game folder itself or the steamapps\common folder above it.
function Resolve-Game($path) {
    foreach ($g in @($path, (Join-Path $path 'LemnisGate'))) {
        if (Test-Path (Join-Path $g 'LemnisGate\Binaries\Win64\LemnisGate-Win64-Shipping.exe')) { return $g }
    }
    return $null
}

function Pick-Game {
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = 'Select your Lemnis Gate folder (steamapps\common\LemnisGate)'
    $dialog.ShowNewFolderButton = $false
    $found = Find-SteamGame
    if ($found) { $dialog.SelectedPath = $found }
    while ($true) {
        if ($dialog.ShowDialog() -ne 'OK') { exit 1 }
        $game = Resolve-Game $dialog.SelectedPath
        if ($game) { return $game }
        Show "That folder doesn't contain Lemnis Gate.`n`nPick the folder that contains LemnisGate.exe (usually steamapps\common\LemnisGate)." 'Warning'
    }
}

function Enable-DevMode {
    $dir = Split-Path -Parent $GameIni
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
    $text = if (Test-Path $GameIni) { [IO.File]::ReadAllText($GameIni) } else { '' }
    if ($text -match '(?m)^\s*EnvironmentType\s*=\s*DEV\s*$') { return 'already on' }
    if ($text.Contains($DevSection)) {
        $text = $text.Replace($DevSection, "$DevSection`r`nEnvironmentType=DEV")
    } else {
        if ($text.Length -gt 0 -and -not $text.EndsWith("`n")) { $text += "`r`n" }
        $text += "$DevSection`r`nEnvironmentType=DEV`r`n"
    }
    [IO.File]::WriteAllText($GameIni, $text)
    return 'turned on'
}

function Install {
    $game = Pick-Game
    $win64 = Join-Path $game 'LemnisGate\Binaries\Win64'
    $paks = Join-Path $game 'LemnisGate\Content\Paks'
    $exe = Join-Path $win64 'LemnisGate-Win64-Shipping.exe'

    $mods = @(Get-ChildItem -Path $Here -Filter 'SalvageOps_*_P.pak')
    if ($mods.Count -eq 0) { Show "No texture pak found next to the installer." 'Error'; exit 1 }
    foreach ($p in $mods) { Copy-Item $p.FullName $paks -Force }
    Set-Content -Path (Join-Path $win64 'steam_appid.txt') -Value $AppId -NoNewline -Encoding Ascii
    $dev = Enable-DevMode

    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($ShortcutPath)
    $lnk.TargetPath = $exe
    $lnk.WorkingDirectory = $win64
    $lnk.IconLocation = (Join-Path $game 'LemnisGate.exe') + ',0'
    $lnk.Description = 'Lemnis Gate with Salvage Ops map textures (no EasyAntiCheat)'
    $lnk.Save()

    Show ("Installed into:`n$game`n`n" +
          "- Map textures: $($mods.Count) pak(s) copied`n" +
          "- Developer mode (P2P menu): $dev`n" +
          "- Desktop shortcut: Lemnis Gate (Salvage Ops)`n`n" +
          "Start the game with the desktop shortcut while Steam is running. " +
          "Launching through Steam starts EasyAntiCheat, which hides the textures.`n`n" +
          "Everyone in a match should start the game the same way.")
}

function Remove-Install {
    $game = Pick-Game
    $removed = @()
    foreach ($p in @(Get-ChildItem -Path (Join-Path $game 'LemnisGate\Content\Paks') -Recurse -Filter 'SalvageOps_*_P.pak')) {
        Remove-Item $p.FullName -Force; $removed += $p.Name
    }
    $appid = Join-Path $game 'LemnisGate\Binaries\Win64\steam_appid.txt'
    if ((Test-Path $appid) -and ((Get-Content $appid -Raw).Trim() -eq $AppId)) { Remove-Item $appid -Force; $removed += 'steam_appid.txt' }
    if (Test-Path $ShortcutPath) { Remove-Item $ShortcutPath -Force; $removed += 'desktop shortcut' }
    $list = if ($removed.Count) { ($removed | ForEach-Object { "- $_" }) -join "`n" } else { '(nothing was installed)' }
    Show ("Removed:`n$list`n`nDeveloper mode in Game.ini was left on, so the P2P menu still works when launching through Steam.")
}

try {
    if ($Uninstall) { Remove-Install } else { Install }
} catch [System.UnauthorizedAccessException] {
    Show "Windows blocked writing to the game folder.`n`nRight-click Install.bat and choose 'Run as administrator'.`n`n$($_.Exception.Message)" 'Error'
    exit 1
} catch {
    Show "Something went wrong:`n`n$($_.Exception.Message)" 'Error'
    exit 1
}
